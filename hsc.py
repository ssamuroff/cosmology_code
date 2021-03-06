import numpy as np
import fitsio as fi
import os
import math
import copy
import glob
import galsim
import pylab as plt
plt.switch_backend('agg')

patches_all = ['0,2',  '1,2',  '1,7',  '2,4',  '3,1',  '3,6',  '4,2',  '4,7', '5,3',  '5,8',  '6,4',  '7,0',  '7,5',  '8,2',  '8,7', '0,3',  '1,3',  '2,0',  '2,5',  '3,2',  '3,7',  '4,3',  '4,8',  '5,4',  '6,0',  '6,5',  '7,1',  '7,6',  '8,3', '0,4',  '1,4',  '2,1',  '2,6',  '3,3',  '3,8',  '4,4',  '5,0',  '5,5',  '6,1',  '6,6',  '7,2',  '7,7',  '8,4', '0,5',  '1,5',  '2,2',  '2,7',  '3,4',  '4,0',  '4,5',  '5,1',  '5,6',  '6,2',  '6,7',  '7,3',  '7,8',  '8,5', '1,1',  '1,6',  '2,3',  '3,0',  '3,5',  '4,1',  '4,6',  '5,2',  '5,7',  '6,3',  '6,8',  '7,4',  '8,1',  '8,6']


class cosmos:
	def __init__(self,catpath='/home/rmandelb.proj/data-shared/HSC/cosmos/parent_best_processed/real_galaxy_catalog_best.fits', cutouts='/global/cscratch1/sd/sws/hsc/cutouts/'):
		self.paths = {}
		if os.path.exists(catpath):
			self.cat = fi.FITS(catpath)[1].read()
		else:
			print 'Catalogue path does not exist'
			print catpath
		self.paths['cutouts'] = cutouts 
		self.paths['catalogue'] = catpath

	def hst_profile(self, i):
		self.source = galsim.RealGalaxyCatalog(self.paths['catalogue'])

	def make_galsim_catalogue(self, band='r', verbose=True, target='real_galaxy_catalog_hsc_%c.fits', batches=[]):
		# Create a copy of the catalogue to write to
		dt = np.dtype([('IDENT', '>i4'), ('RA', '>f8'), ('DEC', '>f8'), ('MAG', '>f8'), ('BAND', 'S5'), ('WEIGHT', '>f8'), ('GAL_FILENAME', 'S200'), ('PSF_FILENAME', 'S200'), ('GAL_HDU', '>i4'), ('PSF_HDU', '>i4'), ('PIXEL_SCALE', '>f8'), ('NOISE_MEAN', '>f8'), ('NOISE_VARIANCE', '>f8'), ('NOISE_FILENAME', 'S26')])
		newcat = np.zeros(self.cat.size, dtype=dt)

		batch = 0
		nrow = 0
		for i,row in enumerate(self.cat):

			if (len(batches)>0):
				if not (batch in batches):
					continue
			nrow+=1

			# adjusting index for ridiculous HSC formatting
			# starts from 2 - vad fan??
			i_perverse = i+2 
			if verbose:
				print i, i_perverse

			p1 = self.construct_path(i_perverse, objtype='masked_galaxies', band=band, batch=batch, filename_only=False)
			newcat['GAL_FILENAME'][i] = '%c/%s/%s'%(band,p1.split('/')[-2],p1.split('/')[-1])
			p2 = self.construct_path(i_perverse, objtype='psf', band=band, batch=batch, filename_only=False)
			newcat['PSF_FILENAME'][i] = '%c/%s/%s'%(band,p2.split('/')[-2],p2.split('/')[-1])
			newcat['GAL_HDU'][i] = -1
			newcat['PSF_HDU'][i] = -1
			newcat['BAND'][i] = band
			newcat['PIXEL_SCALE'][i] = 0.168

			# Copy over the information that doesn't need to change
			cols_done = ['GAL_FILENAME', 'PSF_FILENAME', 'GAL_HDU', 'PSF_HDU', 'BAND', 'PIXEL_SCALE' ]
			for name in newcat.dtype.names:
				if not (name in cols_done): 
					newcat[name] = self.cat[name]

			if (i%899==0) and (i!=0):
				batch+=1

		if '%c' in target:
			target = target%band
		if verbose:
			print 'Saving catalogue to ', target

		# Check whether a FITS files with the same name exists already
		# If it does then delete the old version
		if os.path.exists(target):
			print 'Will overwrite file %s. Are you sure you want to do this?'%target
			import pdb ; pdb.set_trace()
			os.system('rm %s'%target)
		print nrow

		outfits = fi.FITS(target[:nrow], 'rw')
		outfits.write(newcat)
		outfits.close()


	def psf(self, i, band='r', gs=True, batch=0):
		ppath1 = '%s/%c/psf-%d/'%(self.paths['cutouts'],band, batch)
		ppath1 = glob.glob(ppath1+'%d-psf-calexp*-HSC-%c*.fits'%(i, band.upper()))
		ppath1 = ppath1[0]

		psf = fi.FITS(ppath1)[-1].read()

		if not gs:
			return psf
		else:
			import pdb ; pdb.set_trace()

	def construct_path(self, i, objtype='galaxies', band='r', batch=0, filename_only=True):
		if (objtype=='masked_galaxies'):
			mpath1 = '%s/%c/galaxies-%d/'%(self.paths['cutouts'], band, batch)
			mpath1 = glob.glob(mpath1+'%d-*masked*-HSC-%c*.fits'%(i, band.upper()))
			if filename_only:
				mpath1[0] = os.path.basename(mpath1[0])
			try:
				return mpath1[0]
			except:
				import pdb ; pdb.set_trace()
		elif (objtype=='galaxies'):
			path1 = '%s/%c/galaxies-%d/'%(self.paths['cutouts'],band, batch)
			glob.glob(path1+'%d-cutout-HSC-%c*.fits'%(i, band.upper()))
			if filename_only:
				path1[0] = os.path.basename(path1[0])
			return path1[0]
		elif (objtype=='psf'):
			ppath1 = '%s/%c/psf-%d/'%(self.paths['cutouts'],band, batch)
			ppath1 = glob.glob(ppath1+'%d-*psf*-HSC-%c*.fits'%(i, band.upper()))
			if filename_only:
				ppath1[0] = os.path.basename(ppath1[0])
			return ppath1[0]

	def visualise_stamp(self, i, bands=['r','i'], batch=0, cmap='jet', nstamp=0):
		psf=[]
		gal=[]
		mgal=[]

		for band in bands:
			path1 = '%s/%c/galaxies-%d/'%(self.paths['cutouts'],band, batch)
			path1 = glob.glob(path1+'%d-cutout-HSC-%c*.fits'%(i, band.upper()))
			path1 = path1[0]

			ppath1 = '%s/%c/psf-%d/'%(self.paths['cutouts'],band, batch)
			ppath1 = glob.glob(ppath1+'%d-psf-calexp*-HSC-%c*.fits'%(i, band.upper()))
			ppath1 = ppath1[0]

			mpath1 = '%s/%c/galaxies-%d/'%(self.paths['cutouts'],band, batch)
			mpath1 = glob.glob(mpath1+'%d-*masked*-HSC-%c*.fits'%(i, band.upper()))
			mpath1 = mpath1[0]

			psf.append(fi.FITS(ppath1)[-1].read())
			gal.append(fi.FITS(path1)['IMAGE'].read())
			mgal.append(fi.FITS(mpath1)[-1].read())

		j=1
		N = len(psf)
		gmax = gal[0].max()
		gmin = gal[0].min()
		mgmax = mgal[0].max()
		mgmin = mgal[0].min()
		for i,(p,g,masked) in enumerate(zip(psf,gal,mgal)):
			if nstamp>0:
				x0 = g.shape[1]/2
				y0 = g.shape[0]/2
				dx = nstamp/2
				dy = nstamp/2

				g = g[y0-dy:y0+dy, x0-dx:x0+dx ]
				masked = masked[y0-dy:y0+dy, x0-dx:x0+dx ]
			plt.subplot(int('%d%d%d'%(N,3,j)))
			plt.imshow(g, interpolation='none', cmap=cmap)
			plt.clim(mgmin, mgmax)
			print mgmin, mgmax
			j+=1
			plt.subplot(int('%d%d%d'%(N,3,j)))
			plt.imshow(masked, interpolation='none', cmap=cmap)
			plt.clim(mgmin, mgmax)
			j+=1
			plt.subplot(int('%d%d%d'%(N,3,j)))
			plt.imshow(p, interpolation='none', cmap=cmap)
			j+=1





	def export_query(self, band='i', outfile='test_query.txt', window=[0,-1]):

		n = len(self.cat[window[0]:window[1]])
		if n==0:
			print 'Invalid index range'
			return 0

		out = open(outfile, 'wa')
		out.write('#?   ra       dec       sw    sh   filter  image  mask variance type \n')
		for i, col in enumerate(self.cat[window[0]:window[1]]):
			print i
			line = '%f %f 8asec 8asec HSC-%c true true true coadd \n'%(col['RA'], col['DEC'], band.upper())
			out.write(line)
		out.close()
		print 'Done'

	def export_psf_query(self, band='i', outfile='test_psf_query.txt', window=[0,-1]):

		n = len(self.cat[window[0]:window[1]])
		if n==0:
			print 'Invalid index range'
			return 0

		out = open(outfile, 'wa')
		out.write('#?   ra dec filter type rerun \n')
		for i, col in enumerate(self.cat[window[0]:window[1]]):
			print i
			line = '%f %f %c coadd pdr1_udeep \n'%(col['RA'], col['DEC'], band.lower())
			out.write(line)
		out.close()
		print 'Done'







class dr1:
	def __init__(self, data=''):
		import galsim
		print 'Initialised HSC DR1 data wrapper.'
		if data=='':
			data = '/global/cscratch1/sd/sws/hsc/pdr1_udeep_wide_depth_best'

		self.base = data
		print 'will obtain data from %s'%self.base

		self.data = {}
		return None
	def load_coadd(self, band='r', pointing='(8,7)'):
		path = '%s/deepCoadd/HSC-%c/9813/%s'%(self.base,band.upper(),pointing)
		full_path = '%s/calexp-HSC-%c-9813-%s.fits.gz'%(path, band.upper(), pointing)
		filename = os.path.basename(full_path)

		if filename not in self.data.keys():
			self.data[filename]={}

		self.data[filename]['coadd'] = fi.FITS(filename)
		return 0

	def detect(self, band='r', patch='8,7', config='', weights=True):
		# Work out the paths and make a copy of the coadd
		path = '%s/deepCoadd/HSC-%c/9813/%s'%(self.base,band.upper(),patch)
		full_path = '%s/calexp-HSC-%c-9813-%s.fits.gz'%(path, band.upper(), patch)
		filename = os.path.basename(full_path)

		print full_path

		if config=='':
			config='%s/seconfig-sv'%self.base

		os.system('cp %s tmp.fits.gz'%full_path)
		os.system('gunzip tmp.fits.gz')

		# Construct the command
		template = "sex tmp.fits'[1]' -c %s"%(config)

		if weights:
			template += " -WEIGHT_IMAGE tmp.fits'[3]'"

		# Run the command
		print "running: ", template
		os.system(template)

		# Now clean up
		os.system('rm tmp.fits.gz')
		os.system('rm tmp.fits')

		os.system('mv cat.fits %s/calexp-HSC-%c-9813-%s_cat.fits'%(path, band.upper(), patch))
		os.system('mv seg.fits %s/calexp-HSC-%c-9813-%s_seg.fits'%(path, band.upper(), patch))

		print 'Done'

	def bulk_detect(self, bands=['r','i','z'], patches=[]):
		if len(patches)<1:
			patches = patches_all

		for b in bands:
			for p in patches:
				self.detect(band=b, patch=p)

		print "Done all pointings requested"
		return None

	def export_galsim_stamps(self, bands=['r','i','z'], patches=[], mask=False, flags=False, noise_threshold=4, suffix='v5'):

		if len(patches)<1:
			patches = patches_all

		igal=0

		if mask:
			suffix="masked-%s"%suffix
		else:
			suffix="unmasked-%s"%suffix

		if flags:
			suffix+='_flags-%s'%suffix

		for b in bands:

			
			#os.system('rm %s'%out_path2)
			#outfile2 = fi.FITS(out_path2, 'rw')

			
			start=0

			for ip,p in enumerate(patches):

				path = '%s/deepCoadd/HSC-%c/9813/%s'%(self.base,b.upper(),p)
				cat_path = '%s/calexp-HSC-%c-9813-%s_cat.fits'%(path, b.upper(), p)
				cat_path_i = '%s/calexp-HSC-R-9813-%s_cat.fits'%(path, p)
				seg_path = '%s/calexp-HSC-%c-9813-%s_seg.fits'%(path, b.upper(), p)
				coadd_path = '%s/calexp-HSC-%c-9813-%s.fits.gz'%(path, b.upper(), p)
				filename = os.path.basename(cat_path)

				print cat_path

				coadd_data = fi.FITS(coadd_path)['IMAGE'][:,:]
				mask_data = fi.FITS(coadd_path)['MASK'][:,:]
				seg_data = fi.FITS(seg_path)[0][:,:]
				cat_data = fi.FITS(cat_path)[1].read()
				cat_data_i = fi.FITS(cat_path_i)[1].read()


				boxsizes = get_boxsizes(cat_data)
				pixel_count = 0

				out_path = '%s/calexp-HSC-%c-9813-%s_galsim_images_%s.fits'%(path, b.upper(), p, suffix)

				outdat = np.zeros(boxsizes.size, dtype=[('IDENT', int), ("FLAGS", int), ("EDGE_FLAGS", int), ('RA', float), ('DEC', float), ('GAL_FILENAME', 'S100'), ('GAL_HDU', int)])
				outdat['FLAGS']-=9999
				outdat2 = np.empty(30000, dtype=[('IDENT', int), ("FLAGS", int), ("EDGE_FLAGS", int), ('RA', float), ('DEC', float), ('GAL_FILENAME', 'S100'), ('GAL_HDU', int)])
				
				print "Writing cutouts to %s"%out_path
				os.system('rm %s'%out_path)
				outfile = fi.FITS(out_path, 'rw')

				ihdu=0

				for i,row in enumerate(cat_data):
				    x = int(math.floor(cat_data_i['XWIN_IMAGE'][i]+0.5))
				    y = int(math.floor(cat_data_i['YWIN_IMAGE'][i]+0.5))

				    nx = coadd_data.shape[1]
				    ny = coadd_data.shape[0]

				    if ((x<100) or (x>nx-100) or (y<100) or (y>ny-100)):
				    	continue

				    boxsize = boxsizes[i]

				    x0 = x-boxsize/2
				    y0 = y-boxsize/2
				    x1 = x+boxsize/2
				    y1 = y+boxsize/2

				    stamp = coadd_data[y0:y1,x0:x1]
				    seg_stamp = seg_data[y0:y1,x0:x1]

				    if not np.sqrt(stamp.size)==boxsize:
				    	im = galsim.ImageD(coadd_data)
				    	bounds = galsim.BoundsI(xmin=x0,xmax=x1,ymin=y0,ymax=y1)

				    	if (stamp.shape[0]==0) or (stamp.shape[1]==0):
				    		continue  


				    	final = np.zeros((boxsize,boxsize))
				    	seg_final = np.zeros((boxsize,boxsize))
				    	dy0 = abs(min(y0-0, 0))
				    	dx0 = abs(min(x0-0, 0))
				    	dy1 = abs(min(coadd_data.shape[0]-y1, 0))
				    	dx1 = abs(min(coadd_data.shape[1]-x1, 0))


				    	final[dy0:boxsize-dy1, dx0:boxsize-dx1]=stamp
				    	seg_final[dy0:boxsize-dy1, dx0:boxsize-dx1]=seg_stamp

				    else:
				        final = stamp
				        seg_final = seg_stamp	

				    edge_pixels = np.hstack((final[0,:], final[-1,:], final[:,0], final[:,-1]))
				    edge = np.unique(final[seg_final==0]).std()
				    centre = final[seg_final==seg_final[len(seg_final)/2, len(seg_final)/2]].mean()
				    print "Mean edge flux:", edge
				    print "Mean centre flux:", centre

				    if (edge>0.07) or (centre<0.05) or (final[len(seg_final)/2, len(seg_final)/2]<0.01) :
				    	outdat['EDGE_FLAGS'][i]=1

				    if (np.unique(seg_final).size>2):
				    	
				    	if mask:
				    		unmasked_pixels = np.argwhere(seg_final==0)
				    		
				    		sig = np.std(final[:5,])
				    		noise_stamp = np.random.normal(size=final.size).reshape(final.shape) * final[seg_final==0].std()
				    		masked_pixels = np.invert(get_uberseg(seg_final).astype(bool)) #(seg_final!=0) & (seg_final!=seg_final[boxsize/2,boxsize/2])
				    		
				    		final[masked_pixels]=noise_stamp[masked_pixels]

				    number = seg_final[boxsize/2,boxsize/2]
				    if flags:
				    	if number!=0:
				    		flag = cat_data['FLAGS'][cat_data['NUMBER']==number][0]
				    		if (flag>=4):
				    			continue
				    	else:
				    		continue
				    	if outdat['EDGE_FLAGS'][i]==1:
				    		continue

				    outfile.write(final)

				    outdat['IDENT'][i] = seg_final[boxsize/2,boxsize/2]
				    outdat['RA'][i] = row['ALPHAWIN_J2000']
				    outdat['DEC'][i] = row['DELTAWIN_J2000']
				    outdat['GAL_FILENAME'][i] = out_path
				    outdat['GAL_HDU'][i] = ihdu
				    if number!=0:
				    	outdat['FLAGS'] = cat_data['FLAGS'][cat_data['NUMBER']==number][0]
				    else:
				    	outdat['FLAGS'] = 100

				    igal+=1
				    ihdu+=1

				#import pdb ; pdb.set_trace()

				outfile.write(outdat[outdat['FLAGS']!=-9999.])
				outfile[-1].write_key('EXTNAME', 'cat')
				outfile.close()

			#outfile2.write(outdat_all)
			#outfile2.close()

		print "Done"


	def collect_stamps(self, bands=['r','i','z'], patches=[], mask=False):

		if len(patches)<1:
			patches = patches_all

		for b in bands:
			for p in patches:

				path = '%s/deepCoadd/HSC-%c/9813/%s'%(self.base,b.upper(),p)
				cat_path = '%s/calexp-HSC-%c-9813-%s_cat.fits'%(path, b.upper(), p)
				seg_path = '%s/calexp-HSC-%c-9813-%s_seg.fits'%(path, b.upper(), p)
				coadd_path = '%s/calexp-HSC-%c-9813-%s.fits.gz'%(path, b.upper(), p)
				filename = os.path.basename(cat_path)

				print cat_path

				coadd_data = fi.FITS(coadd_path)['IMAGE'][:,:]
				seg_data = fi.FITS(seg_path)[0][:,:]
				cat_data = fi.FITS(cat_path)[1].read()


				boxsizes = get_boxsizes(cat_data)

				image_pixels = []
				seg_pixels = []
				object_data=np.zeros(boxsizes.size, dtype=[('number', int),('start_row', int), ('box_size', int)])
				pixel_count = 0

				for i,row in enumerate(cat_data):
				    x = int(math.floor(row['XWIN_IMAGE']+0.5))
				    y = int(math.floor(row['YWIN_IMAGE']+0.5))

				    boxsize = boxsizes[i]
				    pixel_count+=boxsize*boxsize

				    x0 = x-boxsize/2
				    y0 = y-boxsize/2
				    x1 = x+boxsize/2
				    y1 = y+boxsize/2

				    stamp = coadd_data[y0:y1,x0:x1]
				    seg_stamp = seg_data[y0:y1,x0:x1]

				    if not np.sqrt(stamp.size)==boxsize:
				    	im = galsim.ImageD(coadd_data)
				    	bounds = galsim.BoundsI(xmin=x0,xmax=x1,ymin=y0,ymax=y1)

				    	if (stamp.shape[0]==0) or (stamp.shape[1]==0):
				    		continue  


				    	final = np.zeros((boxsize,boxsize))
				    	seg_final = np.zeros((boxsize,boxsize))
				    	dy0 = abs(min(y0-0, 0))
				    	dx0 = abs(min(x0-0, 0))
				    	dy1 = abs(min(coadd_data.shape[0]-y1, 0))
				    	dx1 = abs(min(coadd_data.shape[1]-x1, 0))


				    	final[dy0:boxsize-dy1, dx0:boxsize-dx1]=stamp
				    	seg_final[dy0:boxsize-dy1, dx0:boxsize-dx1]=seg_stamp

				    else:
				        final = stamp
				        seg_final = seg_stamp	

				    image_pixels.append(final.flatten())
				    seg_pixels.append(seg_final.flatten())
				    object_data['number'][i] = seg_final[boxsize/2,boxsize/2]
				    object_data['start_row'][i] = pixel_count
				    object_data['box_size'][i] = boxsize

				    if mask & np.unique(seg_stamp).size>2:
				    	import pdb ; pdb.set_trace()

				meds_path = '%s/calexp-HSC-%c-9813-%s_meds.fits'%(path, b.upper(), p)
				print "Writing cutouts to %s"%meds_path
				os.system('rm %s'%meds_path)
				meds = fi.FITS(meds_path, 'rw')

				meds.write(np.concatenate(image_pixels))
				meds[-1].write_key('EXTNAME','image_cutouts')
				meds.write(np.concatenate(seg_pixels))
				meds[-1].write_key('EXTNAME','seg_cutouts')
				meds.write(object_data)
				meds[-1].write_key('EXTNAME','object_data')
				meds.close()

		print "Done"






def get_boxsizes(cat_data):
    sig=2*cat_data['FLUX_RADIUS']/2.3548
    epsilon= 1- cat_data['B_WORLD']/cat_data['A_WORLD']
    boxsize = 2*5*sig*(1+epsilon)

    min_boxsize, max_boxsize = 32, 256

    isarray = True
    boxsize = (boxsize+0.5).astype(int)

    # Replace any entries with infinite or overly large or small boxes
    np.putmask(boxsize, np.invert(np.isfinite(boxsize)), 32)
    np.putmask(boxsize, boxsize<min_boxsize, min_boxsize)
    np.putmask(boxsize, boxsize>max_boxsize, max_boxsize)

    # Round up to a factor of 2**N or 3*2**N
    allowed_boxsizes = 2**np.arange(0,1 + np.log(max_boxsize)/np.log(2),1 )
    allowed_boxsizes = np.concatenate((allowed_boxsizes, 3*allowed_boxsizes))
    allowed_boxsizes.sort()
    allowed_boxsizes=allowed_boxsizes[(allowed_boxsizes>=min_boxsize) & (allowed_boxsizes<=max_boxsize) ]

    for i, bs in enumerate(boxsize):
        if bs not in allowed_boxsizes:
            boxsize[i] = allowed_boxsizes[allowed_boxsizes>bs][0] 
        else:
            continue

    return boxsize  


def get_zeropadding(im, bounds):

            # Number of pixels on each axis outside the image bounds
            delta_x_min, delta_x_max, delta_y_min, delta_y_max = 0,0,0,0   
         
            if (bounds.ymin< im.bounds.ymin):
                delta_y_min = im.bounds.ymin - bounds.ymin
                bounds = galsim.BoundsI(ymin=im.bounds.ymin, ymax=bounds.ymax, xmin=bounds.xmin,xmax=bounds.xmax)
            if (bounds.ymax > im.bounds.ymax):
                delta_y_max = bounds.ymax - im.bounds.ymax
                bounds = galsim.BoundsI(ymin=bounds.ymin, ymax=im.bounds.ymax, xmin=bounds.xmin,xmax=bounds.xmax)
            if (bounds.xmin< im.bounds.xmin):
                delta_x_min = im.bounds.xmin - bounds.xmin
                bounds = galsim.BoundsI(ymin=bounds.ymin, ymax=bounds.ymax, xmin=im.bounds.xmin,xmax=bounds.xmax)
            if (bounds.xmax > im.bounds.xmax):
                delta_x_max = bounds.xmax - im.bounds.xmax
                bounds = galsim.BoundsI(ymin=bounds.ymin, ymax=bounds.ymax, xmin=bounds.xmin,xmax=im.bounds.xmax)

            if (bounds.ymin< im.bounds.ymin) or (bounds.ymax > im.bounds.ymax) or (bounds.xmin< im.bounds.xmin) or (bounds.xmax > im.bounds.xmax):
                print 'Stamp bounds are not fully contained by the image bounds'

            return bounds, delta_x_min, delta_x_max, delta_y_min, delta_y_max         


def get_cutout(i, pixels, info):
	i0 = info["start_row"][i]
	b = info["box_size"][i]

	i1 = i0 + b*b

	stamp = pixels[i0:i1].reshape((b,b))

	return stamp



def _make_composite_image(im,seg):

	cim=im.copy()

	coadd_rowcen, coadd_colcen = im.shape[0]/2, im.shape[1]/2
	rowcen, colcen = im.shape[0]/2, im.shape[1]/2

	segid = seg[int(coadd_rowcen),int(coadd_colcen)]

	w=np.where( (seg != segid) & (seg != 0) )
	if w[0].size != 0:
		im[w] = 0.0

	u = rows 
	v = cols

	crow = coadd_rowcen + u
	ccol = coadd_colcen + v

	crow = crow.round().astype('i8')
	ccol = ccol.round().astype('i8')

	crow = crow.clip(0,seg.shape[0]-1)
	ccol = ccol.clip(0,seg.shape[1]-1)

	wbad=np.where( (seg[crow,ccol] != segid ) & (seg[crow,ccol] != 0) )
	if wbad[0].size != 0:
		im[wbad] = 0

	return im


def get_uberseg(seg):
	weight = np.ones(seg.shape)

	#if only have sky and object, then just return
	if len(np.unique(seg)) == 2:
		return weight

	obj_inds = np.where(seg != 0)

	object_number = seg[seg.shape[1]/2, seg.shape[0]/2]

	# Then loop through pixels in seg map, check which obj ind it is closest
	# to.  If the closest obj ind does not correspond to the target, set this
	# pixel in the weight map to zero.
	for i,row in enumerate(seg):
		for j, element in enumerate(row):
			obj_dists = (i-obj_inds[0])**2 + (j-obj_inds[1])**2
			ind_min=np.argmin(obj_dists)

			segval = seg[obj_inds[0][ind_min],obj_inds[1][ind_min]]
			if segval != object_number:
				weight[i,j] = 0.

	return weight







