import numpy as np
import twopoint
import fitsio as fio
import healpy as hp
from numpy.lib.recfunctions import append_fields, rename_fields
from .stage import PipelineStage, NOFZ_NAMES
import subprocess
import os
import warnings

class nofz(PipelineStage):
    name = "nofz"
    inputs = {}
    outputs = {
        "weight"        : "weight.npy"          ,
        "nz_source"     : "nz_source_zbin.npy"  ,
        "nz_lens"       : "nz_lens_zbin.npy"    ,
        "nz_source_txt" : "source.nz"           ,
        "nz_lens_txt"   : "lens.nz"             ,
        "gold_idx"      : "gold_idx.npy"        ,
        "lens_idx"      : "lens_idx.npy"        ,
        "ran_idx"       : "ran_idx.npy"         ,
        "randoms"       : "randoms_zbin.npy"    ,
        "cov_ini"       : "cov.ini"             ,
        "2pt"           : "2pt.fits"            ,
        "metadata"      : "metadata.yaml"
    }

    def get_samples(self):
        if 'colour_bins' in self.params.keys():
            self.samples = self.params['colour_bins'].split()
        else:
            self.samples = ['all']

        print "Colour bins:", self.samples

    def __init__(self, param_file):
        """
        Produces n(z)s from input catalogs.
        """
        super(nofz,self).__init__(param_file)

        self.get_samples()

        # Load data
        if len(self.samples)>1:
            print "you've specifed more than one sample. Will compute p(z) for the first one."
            print self.samples[0]

        self.load_cat(suffix=0, split=self.samples[0])

        if 'pzbin_col' in self.gold.dtype.names:
            print 'ignoring any specified bins, since a bin column has been supplied in gold file'

        # Construct new weight and cache - move to catalog
        if 'weight' in self.pz.dtype.names:
            self.weight = np.sqrt(self.pz['weight'] * self.shape['weight'])
        else:
            self.weight = self.shape['weight']
        filename = self.output_path("weight")
        np.save(filename, np.vstack((self.gold['objid'], self.weight)).T)
        # deal with photo-z weights for lenses later...

        # Setup binning
        if self.params['pdf_type']!='pdf': 
            self.z       = (np.linspace(0.,4.,401)[1:]+np.linspace(0.,4.,401)[:-1])/2.+1e-4 # 1e-4 for buzzard redshift files
            self.dz      = self.z[1]-self.z[0]
            self.binlow  = self.z-self.dz/2.
            self.binhigh = self.z+self.dz/2.
        else:
            self.binlow  = np.array(self.params['pdf_z'][:-1])
            self.binhigh = np.array(self.params['pdf_z'][1:])
            self.z       = (self.binlow+self.binhigh)/2.
            self.dz      = self.binlow[1]-self.binlow[0]

        if hasattr(self.params['zbins'], "__len__"):
            self.tomobins = len(self.params['zbins']) - 1
            self.binedges = self.params['zbins']
        else:
            self.tomobins = self.params['zbins']
            self.binedges = self.find_bin_edges(self.pz['pzbin'][self.mask], self.tomobins, w = self.shape['weight'][self.mask])

        if self.params['lensfile'] != 'None':
            if hasattr(self.params['lens_zbins'], "__len__"):
                self.lens_tomobins = len(self.params['lens_zbins']) - 1
                self.lens_binedges = self.params['lens_zbins']
            else:
                self.lens_tomobins = self.params['lens_zbins']
                self.lens_binedges = self.find_bin_edges(self.lens_pz['pzbin'], self.lens_tomobins, w = self.lens['weight'])

        return

    def run(self):

        # Calculate source n(z)s and write to file
        if self.params['has_sheared']:
            pzbin = [self.pz['pzbin'],self.pz_1p['pzbin'],self.pz_1m['pzbin'],self.pz_2p['pzbin'],self.pz_2m['pzbin']]
        else:
            pzbin = self.pz['pzbin']

        if self.params['pdf_type']!='pdf':        
            zbin, self.nofz = self.build_nofz_bins(
                               self.tomobins,
                               self.binedges,
                               pzbin,
                               self.pz_nofz['pzstack'],
                               self.params['pdf_type'],
                               self.weight,
                               shape=True)
        else:
            pdfs = np.zeros((len(self.pz),len(self.z)))
            for i in range(len(self.z)):
                pdfs[:,i] = self.pz['pzstack'+str(i)]
            zbin, self.nofz = self.build_nofz_bins(
                               self.tomobins,
                               self.binedges,
                               pzbin,
                               pdfs,
                               self.params['pdf_type'],
                               self.weight,
                               shape=True)

        self.get_sigma_e(zbin,self.tomobins,self.shape)
        self.get_neff(zbin,self.tomobins,self.shape)

        if self.params['has_sheared']:
            zbin,zbin_1p,zbin_1m,zbin_2p,zbin_2m=zbin
            np.save(self.output_path("nz_source").replace('nofz/','nofz_%s/'%self.samples[0]), np.vstack((self.gold['objid'], zbin,zbin_1p,zbin_1m,zbin_2p,zbin_2m)).T)
        else:
            np.save(self.output_path("nz_source"), np.vstack((self.gold['objid'], zbin)).T)

        # Calculate lens n(z)s and write to file
        if self.params['lensfile'] != 'None':
            lens_zbin, self.lens_nofz = self.build_nofz_bins(
                                         self.lens_tomobins,
                                         self.lens_binedges,
                                         self.lens_pz['pzbin'],
                                         self.lens_pz['pzstack'],
                                         self.params['lens_pdf_type'],
                                         self.lens['weight'])
            np.save(self.output_path("nz_lens")  , np.vstack((self.lens['objid'], lens_zbin)).T)

            ran_binning = np.digitize(self.randoms['ranbincol'], self.lens_binedges, right=True) - 1
            np.save(self.output_path("randoms"), ran_binning)

            self.get_lens_neff(lens_zbin,self.lens_tomobins,self.lens)


    def write(self):
        """
        Write lens and source n(z)s to fits file for tomographic and non-tomographic cases.
        """

        nz_source = twopoint.NumberDensity(
                     NOFZ_NAMES[0],
                     self.binlow, 
                     self.z, 
                     self.binhigh, 
                     [self.nofz[i,:] for i in range(self.tomobins)])

        nz_source.ngal      = self.neff
        nz_source.sigma_e   = self.sigma_e
        nz_source.area      = self.area
        kernels             = [nz_source]
        np.savetxt(self.output_path("nz_source_txt"), np.vstack((self.binlow, self.nofz)).T)

        if self.params['lensfile'] != 'None':
            nz_lens      = twopoint.NumberDensity(
                            NOFZ_NAMES[1], 
                            self.binlow, 
                            self.z, 
                            self.binhigh, 
                            [self.lens_nofz[i,:] for i in range(self.lens_tomobins)])
            nz_lens.ngal = self.lens_neff
            nz_lens.area = self.area
            kernels.append(nz_lens)
            np.savetxt(self.output_path("nz_lens_txt"), np.vstack((self.binlow, self.lens_nofz)).T)

        data             = twopoint.TwoPointFile([], kernels, None, None)
        data.to_fits(self.output_path("2pt"), clobber=True)

        self.write_metadata()

    def write_metadata(self):
        import yaml
        data = {
            "neff": self.neff,
            "neffc": self.neffc,
            "tomobins": self.tomobins,
            "sigma_e": self.sigma_e,
            "sigma_ec": self.sigma_ec,
            "area": self.area,
            "repository_version:": find_git_hash(),
        }
        if 'pzbin_col' in self.gold.dtype.names:
            data["source_bins"] = "gold_file_bins"
        else:
            if type(self.binedges) is list:
                data.update({ "source_bins" : self.binedges })
            else:
                data.update({ "source_bins" : self.binedges.tolist() })

        if self.params['lensfile'] != 'None':
            data.update({ "lens_neff" : self.lens_neff,
                          "lens_tomobins" : self.lens_tomobins,
                          "lens_bins" : self.lens_binedges })
        print data
        filename = self.output_path('metadata')
        open(filename, 'w').write(yaml.dump(data))


    def load_array(self,d,file):


        if self.params['has_sheared'] & (file=='shapefile'):
            d['flags_1p'] = 'flags_select_1p'
            d['flags_1m'] = 'flags_select_1m'
            d['flags_2p'] = 'flags_select_2p'
            d['flags_2m'] = 'flags_select_2m'

        if self.params['pdf_type']=='pdf':
            keys = [key for key in d.keys() if (d[key] is not None)&(key is not 'pzstack')]
        else:
            keys = [key for key in d.keys() if (d[key] is not None)]

        if 'objid' in keys:
            dtypes = [('objid','i8')]
        else:
            raise ValueError('missing object id in '+file)
        dtypes += [(key,'f8') for key in keys if (key is not 'objid')]
        if self.params['pdf_type']=='pdf':
            dtypes  += [('pzstack_'+str(i),'f8') for i in range(len(self.params['pdf_z']))]

        fits = fio.FITS(self.params[file])[-1]
        array = fits.read(columns=[d[key] for key in keys])

        array = rename_fields(array,{v: k for k, v in d.iteritems()})

        if ('weight' not in array.dtype.names) & (file=='shapefile'):
            array = append_fields(array, 'weight', np.ones(len(array)), usemask=False)

        if self.params['pdf_type']=='pdf':
            for i in range(len(self.params['pdf_z'])):
                array['pzstack'+str(i)]=fits.read(columns=d['pzstack']+str(i))

        if np.any(np.diff(array['objid']) < 1):
            raise ValueError('misordered or duplicate ids in '+file) 

        return array

    def get_im3shape_type(self,shape,gtype):
        import pdb ; pdb.set_trace()
        if gtype.lower()=='bulge':
            return (shape['is_bulge']==1)
        else:
            return (shape['is_bulge']==0) 

    def get_type_split(self, sample, shape, pz, pz_1p, pz_1m, pz_2p, pz_2m):
        if sample=='':
            sample = 0
        else:
            sample = int(sample)-1
        gt = self.samples[sample].split("_")

        print "Cutting to galaxy type",gt

        # If we need to split into bright/faint subsets, then include this in the mask first
        if len(gt)>1:
            subpop = gt[0]
            galaxy_type = gt[1]

            r = 30 - 2.5 * np.log10(shape["flux_r"])
            rp1,rm1 = 30 - 2.5 * np.log10(shape["flux_r_1p"]), 30 - 2.5 * np.log10(shape["flux_r_1m"])
            rp2,rm2 = 30 - 2.5 * np.log10(shape["flux_r_2p"]), 30 - 2.5 * np.log10(shape["flux_r_2m"])
            median_r = np.median(r[shape["flags"]==0])
            if (subpop.lower()=="bright"):
                mag_mask = (r<median_r), (rp1<median_r), (rm1<median_r), (rp2<median_r), (rm2<median_r)
            elif (subpop.lower()=="faint"):
                mag_mask = (r>median_r), (rp1>median_r), (rm1>median_r), (rp2>median_r), (rm2>median_r)
        else:
            galaxy_type=gt[0]
            mag_mask = [np.ones(pz["t_bpz"].size).astype(bool)]*5

        # Select either early- or late-type galaxies
        if galaxy_type=='early':
            mask = [(pz['t_bpz']<1), (pz_1p['t_bpz']<1), (pz_1m['t_bpz']<1), (pz_2p['t_bpz']<1), (pz_2m['t_bpz']<1)]
        elif galaxy_type=='late':
            mask =  [(pz['t_bpz']>=1), (pz_1p['t_bpz']>=1), (pz_1m['t_bpz']>=1), (pz_2p['t_bpz']>=1), (pz_2m['t_bpz']>=1)]
        elif galaxy_type=='all':
            mask = [np.ones(pz["t_bpz"].size).astype(bool)]*5
        
        final_mask = []
        for (m1,m2) in zip(mask,mag_mask):
            final_mask.append(m1&m2)

        return tuple(final_mask)

    def load_cat(self, split="all", suffix=0):
        if suffix==0:
            suffix = ""
        else:
            suffix = "%d"%(suffix+1)

        import time
        import importlib
        col = importlib.import_module('.'+self.params['dict_file'],'pipeline')

        t0 = time.time()

        gold      = self.load_array(col.gold_dict, 'goldfile')
        print 'Done goldfile',time.time()-t0, gold.dtype.names

        shape     = self.load_array(col.shape_dict, 'shapefile')

        print 'Done shapefile',time.time()-t0,shape.dtype.names
        pz        = self.load_array(col.pz_bin_dict, 'photozfile')
        print 'Done pzfile',time.time()-t0, pz.dtype.names
        if self.params['has_sheared']:
            pz_1p = self.load_array(col.pz_bin_dict, 'photozfile_1p')
            print 'Done pz1pfile',time.time()-t0, pz_1p.dtype.names
            pz_1m = self.load_array(col.pz_bin_dict, 'photozfile_1m')
            print 'Done pz1mfile',time.time()-t0, pz_1m.dtype.names
            pz_2p = self.load_array(col.pz_bin_dict, 'photozfile_2p')
            print 'Done pz2pfile',time.time()-t0, pz_2p.dtype.names
            pz_2m = self.load_array(col.pz_bin_dict, 'photozfile_2m')
            print 'Done pz2mfile',time.time()-t0, pz_2m.dtype.names
        pz_nofz   = self.load_array(col.pz_stack_dict, 'photozfile_nz')
        print 'Done pznofzfile',time.time()-t0, pz_nofz.dtype.names
        if self.params['lensfile'] != 'None':
            lens      = self.load_array(col.lens_dict, 'lensfile')
            print 'Done lensfile',time.time()-t0,lens.dtype.names
            lens_pz   = self.load_array(col.lens_pz_dict, 'lensfile')
            print 'Done lens_pzfile',time.time()-t0,lens_pz.dtype.names

        if 'm1' not in shape.dtype.names:
            shape = append_fields(shape, 'm1', shape['m2'], usemask=False)
        if 'm2' not in shape.dtype.names:
            shape = append_fields(shape, 'm2', shape['m1'], usemask=False)
        if self.params['oneplusm']==False:
            print 'converting m to 1+m'
            shape['m1'] = np.copy(shape['m1'])+1.
            shape['m2'] = np.copy(shape['m2'])+1.
        if 'c1' in shape.dtype.names:
            shape['e1'] -= shape['c1']
            shape['e2'] -= shape['c2']
            shape['c1'] = None
            shape['c2'] = None
        if self.params['flip_e2']==True:
            print 'flipping e2'
            shape['e2']*=-1
        if self.params['lensfile'] != 'None':
            if 'pzbin' not in lens_pz.dtype.names:
                lens_pz = append_fields(lens_pz, 'pzbin', lens_pz['pzstack'], usemask=False)
            if 'pzstack' not in lens_pz.dtype.names:
                lens_pz = append_fields(lens_pz, 'pzstack', lens_pz['pzbin'], usemask=False)

        if not ((len(gold)==len(shape))
            & (len(gold)==len(pz))
            & (len(gold)==len(pz_nofz))):
            raise ValueError('shape, gold, or photoz length mismatch')
        if self.params['has_sheared']:
            if not ((len(gold)==len(pz_1p))
                & (len(gold)==len(pz_1m))
                & (len(gold)==len(pz_2p))
                & (len(gold)==len(pz_2m))):
                raise ValueError('shape, gold, or photoz length mismatch')        
        if self.params['lensfile'] != 'None':
            if (len(lens)!=len(lens_pz)):
                raise ValueError('lens and lens_pz length mismatch') 

        if self.params['lensfile'] != 'None':
            keys = [key for key in col.ran_dict.keys() if (col.ran_dict[key] is not None)]
            fits = fio.FITS(self.params['randomfile'])[-1]

            dtypes=[(key,'f8') for key in keys]
            randoms =  np.empty(fits.read_header()['NAXIS2'], dtype = dtypes)
            for key in keys:
                randoms[key]=fits.read(columns=[col.ran_dict[key]])

        if self.params['test_run']==True:
            idx = np.load(self.input_path("gold_idx"))
            gol    = gold[idx]
            shape   = shape[idx]
            pz      = pz[idx]
            pz_nofz = pz_nofz[idx]
            if self.params['has_sheared']:
                pz_1p   = pz_1p[idx]
                pz_1m   = pz_1m[idx]
                pz_2p   = pz_2p[idx]
                pz_2m   = pz_2m[idx]
            if self.params['lensfile'] != 'None':
                idx = np.load(self.input_path("lens_idx"))
                lens    = lens[idx]
                lens_pz = lens_pz[idx]
                idx = np.load(self.input_path("ran_idx"))
                randoms = randoms[idx]

        if 'pzbin_col' in gold.dtype.names:
            mask = (gold['pzbin_col'] >= 0)
        else:
            mask = (pz['pzbin'] > self.params['zlims'][0]) & (pz['pzbin'] <= self.params['zlims'][1])
            if self.params['has_sheared']:
                mask_1p = (pz_1p['pzbin'] > self.params['zlims'][0]) & (pz_1p['pzbin'] <= self.params['zlims'][1])
                mask_1m = (pz_1m['pzbin'] > self.params['zlims'][0]) & (pz_1m['pzbin'] <= self.params['zlims'][1])
                mask_2p = (pz_2p['pzbin'] > self.params['zlims'][0]) & (pz_2p['pzbin'] <= self.params['zlims'][1])
                mask_2m = (pz_2m['pzbin'] > self.params['zlims'][0]) & (pz_2m['pzbin'] <= self.params['zlims'][1])

        if 'i3s_type' in self.params.keys():
            type_mask = self.get_im3shape_type(shape, self.params['i3s_type'])
            mask = mask & type_mask

        if (split!='all'):
            type_mask, tmask1p, tmask1m, tmask2p, tmask2m  = self.get_type_split(suffix, shape, pz, pz_1p, pz_1m, pz_2p, pz_2m )
            mask = mask & type_mask
            mask_1p = mask & tmask1p
            mask_1m = mask & tmask1m
            mask_2p = mask & tmask2p
            mask_2m = mask & tmask2m

        if 'flags' in shape.dtype.names:
            mask = mask & (shape['flags']==0)
            if self.params['has_sheared']:
                mask_1p = mask_1p & (shape['flags_1p']==0)
                mask_1m = mask_1m & (shape['flags_1m']==0)
                mask_2p = mask_2p & (shape['flags_2p']==0)
                mask_2m = mask_2m & (shape['flags_2m']==0)
        if 'flags' in pz.dtype.names:
            mask = mask & (pz['flags']==0)
            if self.params['has_sheared']:
                mask_1p = mask_1p & (pz_1p['flags']==0)
                mask_1m = mask_1m & (pz_1m['flags']==0)
                mask_2p = mask_2p & (pz_2p['flags']==0)
                mask_2m = mask_2m & (pz_2m['flags']==0)

        print 'hardcoded spt region cut'
        mask = mask & (shape['dec']<-35)
        if self.params['has_sheared']:
            mask_1p = mask_1p & (shape['dec']<-35)
            mask_1m = mask_1m & (shape['dec']<-35)
            mask_2p = mask_2p & (shape['dec']<-35)
            mask_2m = mask_2m & (shape['dec']<-35)

        if 'footprintfile' in self.params.keys():
            print 'cutting catalog to footprintfile'
            footmask = np.in1d(hp.ang2pix(4096, np.pi/2.-np.radians(shape['dec']),np.radians(shape['ra']), nest=False),
                               fio.FITS(self.params['footprintfile'])[-1].read()['HPIX'],assume_unique=False)
            mask = mask & footmask
            if self.params['has_sheared']:
                mask_1p = mask_1p & footmask
                mask_1m = mask_1m & footmask
                mask_2p = mask_2p & footmask
                mask_2m = mask_2m & footmask

        if self.params['has_sheared']:
            full_mask     = mask & mask_1p & mask_1m & mask_2p & mask_2m
            setattr(self, "mask%s"%suffix, mask[full_mask])
            setattr(self, "mask_1p%s"%suffix, mask_1p[full_mask])
            setattr(self, "mask_1m%s"%suffix, mask_1m[full_mask])
            setattr(self, "mask_2p%s"%suffix, mask_2p[full_mask])
            setattr(self, "mask_2m%s"%suffix, mask_2m[full_mask])
        else:
            full_mask  = mask
            setattr(self, "mask%s"%suffix, mask[full_mask])
        setattr(self, "gold%s"%suffix, gold[full_mask])
        setattr(self, "shape%s"%suffix, shape[full_mask])
        setattr(self, "pz%s"%suffix, pz[full_mask])
        setattr(self, "pz_nofz%s"%suffix, pz_nofz[full_mask])
        if self.params['lensfile']!='None': setattr(self, "randoms%s"%suffix,randoms)

        if self.params['has_sheared']:
            full_mask     = mask & mask_1p & mask_1m & mask_2p & mask_2m
            setattr(self, "pz_1p%s"%suffix, pz_1p[full_mask])
            setattr(self, "pz_1m%s"%suffix, pz_1m[full_mask])
            setattr(self, "pz_2p%s"%suffix, pz_2p[full_mask])
            setattr(self, "pz_2m%s"%suffix, pz_2m[full_mask])
            setattr(self, "mask%s"%suffix, mask[full_mask])
            setattr(self, "mask_1p%s"%suffix, mask_1p[full_mask])
            setattr(self, "mask_1m%s"%suffix, mask_1m[full_mask])
            setattr(self, "mask_2p%s"%suffix, mask_2p[full_mask])
            setattr(self, "mask_2m%s"%suffix, mask_2m[full_mask])
        else:
            full_mask  = mask
            setattr(self, "mask%s"%suffix, mask[full_mask])

        return


    def load_data(self):
        """
        Load data files.
        """

        import time
        import importlib
        col = importlib.import_module('.'+self.params['dict_file'],'pipeline')

        # def lowercase_array(arr):
        #     old_names = arr.dtype.names
        #     new_names = [name.lower() for name in old_names]
        #     renames   = dict(zip(old_names, new_names))
        #     return rename_fields(arr, renames)
        t0 = time.time()

        self.gold      = self.load_array(col.gold_dict, 'goldfile')
        print 'Done goldfile',time.time()-t0,self.gold.dtype.names
        self.shape     = self.load_array(col.shape_dict, 'shapefile')
        print 'Done shapefile',time.time()-t0,self.shape.dtype.names
        self.pz        = self.load_array(col.pz_bin_dict, 'photozfile')
        print 'Done pzfile',time.time()-t0,self.pz.dtype.names
        if self.params['has_sheared']:
            self.pz_1p = self.load_array(col.pz_bin_dict, 'photozfile_1p')
            print 'Done pz1pfile',time.time()-t0,self.pz_1p.dtype.names
            self.pz_1m = self.load_array(col.pz_bin_dict, 'photozfile_1m')
            print 'Done pz1mfile',time.time()-t0,self.pz_1m.dtype.names
            self.pz_2p = self.load_array(col.pz_bin_dict, 'photozfile_2p')
            print 'Done pz2pfile',time.time()-t0,self.pz_2p.dtype.names
            self.pz_2m = self.load_array(col.pz_bin_dict, 'photozfile_2m')
            print 'Done pz2mfile',time.time()-t0,self.pz_2m.dtype.names
        self.pz_nofz   = self.load_array(col.pz_stack_dict, 'photozfile_nz')
        print 'Done pznofzfile',time.time()-t0,self.pz_nofz.dtype.names
        if self.params['lensfile'] != 'None':
            self.lens      = self.load_array(col.lens_dict, 'lensfile')
            print 'Done lensfile',time.time()-t0,self.lens.dtype.names
            self.lens_pz   = self.load_array(col.lens_pz_dict, 'lensfile')
            print 'Done lens_pzfile',time.time()-t0,self.lens_pz.dtype.names

        if 'm1' not in self.shape.dtype.names:
            self.shape = append_fields(self.shape, 'm1', self.shape['m2'], usemask=False)
        if 'm2' not in self.shape.dtype.names:
            self.shape = append_fields(self.shape, 'm2', self.shape['m1'], usemask=False)
        if self.params['oneplusm']==False:
            print 'converting m to 1+m'
            self.shape['m1'] = np.copy(self.shape['m1'])+1.
            self.shape['m2'] = np.copy(self.shape['m2'])+1.
        if 'c1' in self.shape.dtype.names:
            self.shape['e1'] -= self.shape['c1']
            self.shape['e2'] -= self.shape['c2']
            self.shape['c1'] = None
            self.shape['c2'] = None
        if self.params['flip_e2']==True:
            print 'flipping e2'
            self.shape['e2']*=-1
        if 'pzbin' not in self.lens_pz.dtype.names:
            self.lens_pz = append_fields(self.lens_pz, 'pzbin', self.lens_pz['pzstack'], usemask=False)
        if 'pzstack' not in self.lens_pz.dtype.names:
            self.lens_pz = append_fields(self.lens_pz, 'pzstack', self.lens_pz['pzbin'], usemask=False)

        if not ((len(self.gold)==len(self.shape))
            & (len(self.gold)==len(self.pz))
            & (len(self.gold)==len(self.pz_nofz))):
            raise ValueError('shape, gold, or photoz length mismatch')
        if self.params['has_sheared']:
            if not ((len(self.gold)==len(self.pz_1p))
                & (len(self.gold)==len(self.pz_1m))
                & (len(self.gold)==len(self.pz_2p))
                & (len(self.gold)==len(self.pz_2m))):
                raise ValueError('shape, gold, or photoz length mismatch')        
        if self.params['lensfile'] != 'None':
            if (len(self.lens)!=len(self.lens_pz)):
                raise ValueError('lens and lens_pz length mismatch') 

        if self.params['lensfile'] != 'None':
            keys = [key for key in col.ran_dict.keys() if (col.ran_dict[key] is not None)]
            fits = fio.FITS(self.params['randomfile'])[-1]

            dtypes=[(key,'f8') for key in keys]
            self.randoms = np.empty(fits.read_header()['NAXIS2'], dtype = dtypes)
            for key in keys:
                self.randoms[key]=fits.read(columns=[col.ran_dict[key]])

        if self.params['test_run']==True:
            idx = np.random.choice(np.arange(len(self.gold)),100000,replace=False)
            np.save(self.output_path("gold_idx"), idx)
            self.gold    = self.gold[idx]
            self.shape   = self.shape[idx]
            self.pz      = self.pz[idx]
            self.pz_nofz = self.pz_nofz[idx]
            if self.params['has_sheared']:
                self.pz_1p   = self.pz_1p[idx]
                self.pz_1m   = self.pz_1m[idx]
                self.pz_2p   = self.pz_2p[idx]
                self.pz_2m   = self.pz_2m[idx]
            if self.params['lensfile'] != 'None':
                idx = np.random.choice(np.arange(len(self.lens)),100000,replace=False)
                np.save(self.output_path("lens_idx"), idx)
                self.lens    = self.lens[idx]
                self.lens_pz = self.lens_pz[idx]
                idx = np.random.choice(np.arange(len(self.randoms)),100000,replace=False)
                np.save(self.output_path("ran_idx"), idx)
                self.randoms = self.randoms[idx]

        if 'pzbin_col' in self.gold.dtype.names:
            mask = (self.gold['pzbin_col'] >= 0)
        else:
            mask = (self.pz['pzbin'] > self.params['zlims'][0]) & (self.pz['pzbin'] <= self.params['zlims'][1])
            if self.params['has_sheared']:
                mask_1p = (self.pz_1p['pzbin'] > self.params['zlims'][0]) & (self.pz_1p['pzbin'] <= self.params['zlims'][1])
                mask_1m = (self.pz_1m['pzbin'] > self.params['zlims'][0]) & (self.pz_1m['pzbin'] <= self.params['zlims'][1])
                mask_2p = (self.pz_2p['pzbin'] > self.params['zlims'][0]) & (self.pz_2p['pzbin'] <= self.params['zlims'][1])
                mask_2m = (self.pz_2m['pzbin'] > self.params['zlims'][0]) & (self.pz_2m['pzbin'] <= self.params['zlims'][1])

        if 'flags' in self.shape.dtype.names:
            mask = mask & (self.shape['flags']==0)
            if self.params['has_sheared']:
                mask_1p = mask_1p & (self.shape['flags_1p']==0)
                mask_1m = mask_1m & (self.shape['flags_1m']==0)
                mask_2p = mask_2p & (self.shape['flags_2p']==0)
                mask_2m = mask_2m & (self.shape['flags_2m']==0)
        if 'flags' in self.pz.dtype.names:
            mask = mask & (self.pz['flags']==0)
            if self.params['has_sheared']:
                mask_1p = mask_1p & (self.pz_1p['flags']==0)
                mask_1m = mask_1m & (self.pz_1m['flags']==0)
                mask_2p = mask_2p & (self.pz_2p['flags']==0)
                mask_2m = mask_2m & (self.pz_2m['flags']==0)

        print 'hardcoded spt region cut'
        mask = mask & (self.shape['dec']<-35)
        if self.params['has_sheared']:
            mask_1p = mask_1p & (self.shape['dec']<-35)
            mask_1m = mask_1m & (self.shape['dec']<-35)
            mask_2p = mask_2p & (self.shape['dec']<-35)
            mask_2m = mask_2m & (self.shape['dec']<-35)

        print np.sum(mask)
        if 'footprintfile' in self.params.keys():
            print 'cutting catalog to footprintfile'
            footmask = np.in1d(hp.ang2pix(4096, np.pi/2.-np.radians(self.shape['dec']),np.radians(self.shape['ra']), nest=False),
                               fio.FITS(self.params['footprintfile'])[-1].read()['HPIX'],assume_unique=False)
            mask = mask & footmask
            if self.params['has_sheared']:
                mask_1p = mask_1p & footmask
                mask_1m = mask_1m & footmask
                mask_2p = mask_2p & footmask
                mask_2m = mask_2m & footmask

        print np.sum(mask)

        if self.params['has_sheared']:
            full_mask     = mask & mask_1p & mask_1m & mask_2p & mask_2m
            self.pz_1p    = self.pz_1p[full_mask]
            self.pz_1m    = self.pz_1m[full_mask]
            self.pz_2p    = self.pz_2p[full_mask]
            self.pz_2m    = self.pz_2m[full_mask]
            self.mask     = mask[full_mask]
            self.mask_1p  = mask_1p[full_mask]
            self.mask_1m  = mask_1m[full_mask]
            self.mask_2p  = mask_2p[full_mask]
            self.mask_2m  = mask_2m[full_mask]
        else:
            full_mask  = mask
            self.mask  = mask[full_mask]
        self.gold      = self.gold[full_mask]
        self.shape     = self.shape[full_mask]
        self.pz        = self.pz[full_mask]
        self.pz_nofz   = self.pz_nofz[full_mask]

        return 

    def build_nofz_bins(self, zbins, edge, bin_col, stack_col, pdf_type, weight,shape=False):
        """
        Build an n(z), non-tomographic [:,0] and tomographic [:,1:].
        """

        if shape&(self.params['has_sheared']):
            if 'pzbin_col' in self.gold.dtype.names:
                xbins = self.gold['pzbin_col']
            else:
                xbins0=[]
                for x in bin_col:
                    xbins0.append(np.digitize(x, edge, right=True) - 1)
                xbins = xbins0[0]
        else:
            if 'pzbin_col' in self.gold.dtype.names:
                xbins0 = self.gold['pzbin_col']
            else:
                xbins0 = np.digitize(bin_col, edge, right=True) - 1
            xbins=xbins0

        # Stack n(z)
        nofz  = np.zeros((zbins, len(self.z)))

        # MC Sample of pdf or redmagic (if redmagic, takes random draw from gaussian of width 0.01)
        if (pdf_type == 'sample') | (pdf_type == 'rm'):
            if pdf_type == 'rm':
                stack_col = np.random.normal(stack_col, self.lens_pz['pzerr']*np.ones(len(stack_col)))
            for i in range(zbins):
                mask        =  (xbins == i)
                if shape:
                    mask = mask&self.mask
                    if self.params['has_sheared']:
                        mask_1p = (xbins0[1] == i)&self.mask_1p
                        mask_1m = (xbins0[2] == i)&self.mask_1m
                        mask_2p = (xbins0[3] == i)&self.mask_2p
                        mask_2m = (xbins0[4] == i)&self.mask_2m
                        m1   = np.mean(self.shape['m1'][mask&self.mask])
                        m2   = np.mean(self.shape['m2'][mask&self.mask])
                        m1   += (np.mean(self.shape['e1'][mask_1p&self.mask_1p]) - np.mean(self.shape['e1'][mask_1m&self.mask_1m])) / (2.*self.params['dg'])
                        m2   += (np.mean(self.shape['e2'][mask_2p&self.mask_2p]) - np.mean(self.shape['e2'][mask_2m&self.mask_2m])) / (2.*self.params['dg'])
                        m1   = m1*np.ones(len(mask))
                        m2   = m2*np.ones(len(mask))
                    else:
                        m1 = self.shape['m1']
                        m2 = self.shape['m2']
                    weight *= (m1+m2)/2.
                nofz[i,:],b =  np.histogram(stack_col[mask], bins=np.append(self.binlow, self.binhigh[-1]), weights=weight[mask])
                nofz[i,:]   /= np.sum(nofz[i,:]) * self.dz

        # Stacking pdfs
        elif pdf_type == 'pdf':
            for i in xrange(zbins):
                mask      =  (xbins == i)
                if shape:
                    mask = mask&self.mask
                nofz[i,:] =  np.sum((stack_col[mask].T * weight[mask]).T, axis=0)
                nofz[i,:] /= np.sum(nofz[i,:]) * self.dz

        return xbins0, nofz

    def find_bin_edges(self, x, nbins, w=None):
        """
        For an array x, returns the boundaries of nbins equal (possibly weighted by w) bins.
        From github.com/matroxel/destest.
        """

        if w is None:
            xs = np.sort(x)
            r  = np.linspace(0., 1., nbins + 1.) * (len(x) - 1)
            return xs[r.astype(int)]

        fail = False
        ww   = np.sum(w) / nbins
        i    = np.argsort(x)
        k    = np.linspace(0.,1., nbins + 1.) * (len(x) - 1)
        k    = k.astype(int)
        r    = np.zeros((nbins + 1))
        ist  = 0
        for j in xrange(1,nbins):
            if k[j]  < r[j-1]:
                print 'Random weight approx. failed - attempting brute force approach'
                fail = True
                break

            w0 = np.sum(w[i[ist:k[j]]])
            if w0 <= ww:
                for l in xrange(k[j], len(x)):
                    w0 += w[i[l]]
                    if w0 > ww:
                        r[j] = x[i[l]]
                        ist  = l
                        break
            else:
                for l in xrange(k[j], 0, -1):
                    w0 -= w[i[l]]
                    if w0 < ww:
                        r[j] = x[i[l]]
                        ist  = l
                        break

        if fail:
            ist = np.zeros((nbins+1))
            ist[0]=0
            for j in xrange(1, nbins):
                wsum = 0.
                for k in xrange(ist[j-1].astype(int), len(x)):
                    wsum += w[i[k]]
                    if wsum > ww:
                        r[j]   = x[i[k-1]]
                        ist[j] = k
                        break

        r[0]  = x[i[0]]
        r[-1] = x[i[-1]]

        return r

    def get_neff(self, zbin, tomobins, cat):
        """
        Calculate neff for catalog.
        """

        if not hasattr(self,'area'):
            self.get_area()

        self.neff = []
        self.neffc = []
        for i in range(self.tomobins):
            if self.params['has_sheared']:
                mask = (zbin[0] == i)
                mask_1p = (zbin[1] == i)
                mask_1m = (zbin[2] == i)
                mask_2p = (zbin[3] == i)
                mask_2m = (zbin[4] == i)

                m1   = np.mean(cat['m1'][mask&self.mask])
                m2   = np.mean(cat['m2'][mask&self.mask])
                m1   += (np.mean(cat['e1'][mask_1p&self.mask_1p]) - np.mean(cat['e1'][mask_1m&self.mask_1m])) / (2.*self.params['dg'])
                m2   += (np.mean(cat['e2'][mask_2p&self.mask_2p]) - np.mean(cat['e2'][mask_2m&self.mask_2m])) / (2.*self.params['dg'])
                m1   = m1*np.ones(len(mask))
                m2   = m2*np.ones(len(mask))
            else:
                mask = (zbin == i)
                m1 = cat['m1']
                m2 = cat['m2']

            mask = mask & self.mask

            if self.params['has_sheared']:
                e1  = cat['e1'][mask]
                e2  = cat['e2'][mask]
                w   = cat['weight'][mask]
                s   = (m1[mask]+m2[mask])/2.
                var = cat['cov00'][mask] + cat['cov11'][mask]
                var[var>2] = 2.
            else:
                e1  = cat['e1'][mask]
                e2  = cat['e2'][mask]
                w   = cat['weight'][mask]
                s = (m1[mask]+m2[mask])/2.
                snvar = 0.24#np.sqrt((cat['e1'][mask][cat['snr'][mask]>100].var()+cat['e2'][mask][cat['snr'][mask]>100].var())/2.)
                var = 1./w - snvar**2
                var[var < 0.] = 0.
                w[w > snvar**-2] = snvar**-2

            a    = np.sum(w)**2
            b    = np.sum(w**2)
            c    = self.area * 60. * 60.

            self.neff.append( a/b/c )
            self.neffc.append( ((self.sigma_ec[i]**2 * np.sum(w * s)**2) / np.sum(w**2 * (s**2 * self.sigma_ec[i]**2 + var/2.))) / self.area / 60**2 )

            print 'ratio',self.sigma_e[i]**2/self.neff[-1],self.sigma_ec[i]**2/self.neffc[-1]

        return

    def get_lens_neff(self, zbin, tomobins, cat):
        """
        Calculate neff for catalog.
        """

        if not hasattr(self,'area'):
            self.get_area()

        self.lens_neff = []
        for i in range(tomobins):
          mask = (zbin == i)
          a    = np.sum(cat['weight'][mask])**2
          b    = np.sum(cat['weight'][mask]**2)
          c    = self.area * 60. * 60.

          self.lens_neff.append( a/b/c )

        return


    def get_sigma_e(self, zbin, tomobins, cat):
        """
        Calculate sigma_e for shape catalog.
        """

        if not hasattr(self,'area'):
            self.get_area()

        self.sigma_e = []
        self.sigma_ec = []
        for i in range(tomobins):
            if self.params['has_sheared']:
                mask = (zbin[0] == i)
                mask_1p = (zbin[1] == i)
                mask_1m = (zbin[2] == i)
                mask_2p = (zbin[3] == i)
                mask_2m = (zbin[4] == i)

                m1   = np.mean(cat['m1'][mask&self.mask])
                m2   = np.mean(cat['m2'][mask&self.mask])
                m1   += (np.mean(cat['e1'][mask_1p&self.mask_1p]) - np.mean(cat['e1'][mask_1m&self.mask_1m])) / (2.*self.params['dg'])
                m2   += (np.mean(cat['e2'][mask_2p&self.mask_2p]) - np.mean(cat['e2'][mask_2m&self.mask_2m])) / (2.*self.params['dg'])
                m1   = m1*np.ones(len(mask))
                m2   = m2*np.ones(len(mask))
            else:
                mask = (zbin == i)
                m1 = cat['m1']
                m2 = cat['m2']

            mask = mask & self.mask

            if self.params['has_sheared']:
                e1  = cat['e1'][mask]
                e2  = cat['e2'][mask]
                w   = cat['weight'][mask]
                s   = (m1[mask]+m2[mask])/2.
                var = cat['cov00'][mask] + cat['cov11'][mask]
                var[var>2] = 2.
            else:
                e1  = cat['e1'][mask]
                e2  = cat['e2'][mask]
                w   = cat['weight'][mask]
                s = (m1[mask]+m2[mask])/2.
                snvar = 0.24#np.sqrt((cat['e1'][mask][cat['snr'][mask]>100].var()+cat['e2'][mask][cat['snr'][mask]>100].var())/2.)
                print i,'snvar',snvar
                var = 1./w - snvar**2
                var[var < 0.] = 0.
                w[w > snvar**-2] = snvar**-2
                print 'var',var.min(),var.max()

            a1 = np.sum(w**2 * e1**2)
            a2 = np.sum(w**2 * e2**2)
            b  = np.sum(w**2)
            c  = np.sum(w * s)
            d  = np.sum(w)

            self.sigma_e.append( np.sqrt( (a1/c**2 + a2/c**2) * (d**2/b) / 2. ) )
            self.sigma_ec.append( np.sqrt( np.sum(w**2 * (e1**2 + e2**2 - var)) / (2.*np.sum(w**2 * s**2)) ) )
            print np.sum(e1**2 + e2**2 - var),np.max(e1**2 + e2**2 - var),np.min(e1**2 + e2**2 - var)

        return

    def get_area(self):

        if hasattr(self,'area'):
            return

        if self.params['area']=='None':

            import healpy as hp

            pix=hp.ang2pix(4096, np.pi/2.-np.radians(self.shape['dec']),np.radians(self.shape['ra']), nest=True)
            area=hp.nside2pixarea(4096)*(180./np.pi)**2
            mask=np.bincount(pix)>0
            self.area=np.sum(mask)*area
            self.area=float(self.area)
            print self.area
        
        else:

            self.area = self.params['area']

        return 

def find_git_hash():
    try:
        dirname = os.path.dirname(os.path.abspath(__file__))
        head = subprocess.check_output("cd {0}; git show-ref HEADS".format(dirname), shell=True)
    except subprocess.CalledProcessError:
        head = "UNKNOWN"
        warnings.warn("Unable to find git repository commit ID in {}".format(dirname))
    return head.split()[0]


