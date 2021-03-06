import numpy as np
import pyfits as pf
import fitsio as fio
import glob
import treecorr as tc
import meds, fitsio
import galsim
import os, math
import py3shape.i3meds as i3meds
import py3shape.options as i3opt
import tools.diagnostics as di
import pylab as plt
import tools.arrays as arr
from plots import im3shape_results_plots as i3s_plots


BLACKLIST_CACHE = {}
PSFEX_CACHE = {}
PSFEX_CACHE_FILENAME = ""

names = {"snr": "snr", "rgp" : "mean_rgpp_rp", "e1": "e1", "e2" : "e2", "iterations":"levmar_iterations", "psf_e1" : "mean_psf_e1", "psf_e2" : "mean_psf_e2", "psf_fwhm": "mean_psf_fwhm", "nflag": "neighbour_flag", "dphi":"dphi"}

sersic_indices={"disc": 1, "bulge": 4}

class shapecat(i3s_plots):
	"""Class for handling im3shape results and,
	   if relevant, truth catalogues.
	"""
	def __init__(self, res=None, truth=None, coadd=False, fit="disc", noisefree=False):
		if res is None and truth is None:
			print "Please specify at least one of res=, truth="
		self.res_path = res
		self.truth_path = truth
		self.coadd_path= coadd

		self.fit = fit
		self.noisefree=noisefree

		self.corr={}

		print "Initialised."

	def load_from_array(self, array, name="res"):
		setattr(self, name, array)

	def load(self, res=True, truth=False, epoch=False,coadd=False, postprocessed=True, keyword="DES", apply_infocuts=True, ext=".fits"):
		
		if res:
			if "%s"%ext in self.res_path:
				files=[self.res_path]
			else:
				files = glob.glob("%s/*%s"%(self.res_path,ext))
			print "%s/*.%s"%(self.res_path,ext)
			single_file=False
			print "loading %d results file(s) from %s"%(len(files),self.res_path)

			if self.noisefree and apply_infocuts:
				self.res = pf.getdata(files[0])
				tmp, noise_free_infocuts = self.get_infocuts(exclude=["chi"], return_string=True)

				noise_free_infocuts = noise_free_infocuts.replace("cuts= ((", "cuts= ((%s['chi2_pixel']>0.004) & (%s['chi2_pixel']<0.2) & (")

			if len(files)>1:
				if apply_infocuts and self.noisefree:
					self.res, self.files, i = di.load_results(res_path =self.res_path, format=ext[1:], apply_infocuts=False, additional_cuts=noise_free_infocuts, keyword=keyword, postprocessed=postprocessed, return_filelist=True)
				else:
					self.res, self.files, i = di.load_results(res_path =self.res_path, format=ext[1:], apply_infocuts=apply_infocuts, keyword=keyword, postprocessed=postprocessed, return_filelist=True)
			else:
				if ext.lower()==".fits":
					self.res = fio.FITS(files[0])[1].read()
				elif ext.lower()==".txt":
					self.res = np.genfromtxt(files[0], names=True)
				self.files=files
				single_file=True
				i=None


		if truth:
			if ".fits" in self.truth_path:
				files=[self.truth_path]
			else:
				files = glob.glob("%s/*.fits*"%self.truth_path)
			single_file=False

			print "loading truth files from %s"%self.truth_path
			if len(files)>1:
				self.truth = di.load_truth(truth_path=self.truth_path, match=self.files, ind=i, res=self.res)
			else:
				self.truth = pf.getdata(files[0])

		if truth and res:
			self.res, self.truth = di.match_results(self.res,self.truth)
			if ("ra" in self.res.dtype.names): 
				if not (self.res["ra"]==self.truth["ra"]).all():
					self.res["ra"] = self.truth["ra"]
					self.res["dec"] = self.truth["dec"]

			print "Found catalogue of %d objects after matching to truth table"%len(self.res)


		if coadd:
			if ".fits" in self.coadd_path:
				files=[self.coadd_path]
			else:
				files = glob.glob("%s/*cat*.fits"%self.coadd_path)
			single_file=False

			print "loading coadd catalogue files from %s"%self.coadd_path
			if len(files)>1:
				print "update code..."
			else:
				self.coadd = pf.getdata(files[0])

			ids = self.res["row_id"]-1
			self.coadd= self.coadd[ids]

		if epoch:
			path = self.res_path.replace("main", "epoch")
			try:
				self.epoch = di.load_epoch(path)
			except:
				self.epoch = di.load_epoch(path.replace("bord", "disc"))

		if hasattr(self, "truth"):
			sel = self.truth["sextractor_pixel_offset"]<1.0
			self.truth = self.truth[sel]
			if hasattr(self, "res"):
				self.res = self.res[sel]
			if coadd:
				self.coadd = self.coadd[sel]

	def add_bpz_cols(self, fil="/share/des/disc3/samuroff/y1/photoz/bpz/NSEVILLA_PHOTOZ_TPL_Y1G103_1_bpz_highzopt_2_9_16.fits", array=None, exclude=None):
		print "Loading BPZ results from %s"%fil
		if array is None:
			bpz = fio.FITS(fil)[1].read()
		else:
			bpz = array

		self.res, bpz = di.match_results(self.res, bpz, name1="coadd_objects_id", name2="coadd_objects_id")

		for colname in bpz.dtype.names:
			if colname=="coadd_objects_id":
				continue
			if exclude is not None:
				if colname in exclude:
					continue
			else:
				print "Adding column: %s"%colname 
				self.res = add_col(self.res, colname, bpz[colname])

	def get_bulge_fraction(self, fcat, split_type="bpz", return_mask=False):
		if "bpz" in split_type:
			sel = fcat["T_B"]<2.0
		if "im3shape" in split_type:
			sel = fcat["bulge_flux"]!=0.0
		if return_mask:
			return 1.0*fcat[sel].shape[0]/fcat.shape[0], sel
		else:
			return 1.0*fcat[sel].shape[0]/fcat.shape[0]

	def get_positions(self, postype):
		"""Extract the position coordinates of objects, either from a truth
		   table or from an im3shape results table."""
		if postype not in ["world", "pixel"]:
			"Please choose a coordinate system ('world' or 'pixel')"

		if postype=="world":
			xname,yname = "ra","dec"
		elif postype=="pixel":
			xname,yname = "X_IMAGE","Y_IMAGE"

		print "Obtained position data from",

		try:
			x,y = self.truth[xname],self.truth[yname]
			print "truth table"
		except:
			try:
				x,y = self.res[xname],self.res[yname]
				print "results table"
			except:
				x,y = self.coadd[xname],self.coadd[yname]
				print "coadd catalogue"

		return x,y


	def hist(self, param, normed=1, histtype="step", alpha=1.0, truth=False, res=True, nbins=25, xlim_upper=None, xlim_lower=None, label=None, colour="purple", infoflags=False, errorflags=False, neighbourflags=False, starflags=False, linestyle="solid", extra_cuts=None):
		"""Plot out a histogram of a particular parameter."""
		colname=names[param]
		sel= self.get_mask(info=infoflags, error=errorflags, stars=starflags, neighbours=neighbourflags)
		try:
			bins = np.linspace(xlim_lower, xlim_upper, nbins)
			plt.xlim(xlim_lower,xlim_upper)
		except:
			bins=nbins

		if not truth:
			data=self.res
		else:
			data=self.truth

		if extra_cuts is None:
			extra_cuts = np.ones_like(data)
		else:
			sel = sel & extra_cuts
		plt.hist(data[colname][sel], bins=bins, histtype=histtype, color=colour, normed=normed, lw=2.0, label=label, linestyle=linestyle, alpha=alpha)

	def get_mask(self, info=True, error=False, stars=False, neighbours=False):
		"""Get the selection mask for either error or info flag cuts."""
		if info:
			seli = self.res["info_flag"]==0
		else:
			seli = np.ones_like(self.res["e1"]).astype(bool)

		if error:
			sele = self.res["error_flag"]==0
		else:
			sele = np.ones_like(self.res["e1"]).astype(bool)

		if stars:
			sels = self.truth["star_flag"]==0
		else:
			sels = np.ones_like(self.res["e1"]).astype(bool)

		if neighbours:
			seln = self.truth["neighbour_flag"]==0
		else:
			seln = np.ones_like(self.res["e1"]).astype(bool)

		sel = (seli & sele & sels & seln)

		print "Mask leaves %d/%d objects."%(len(self.res[sel]), len(self.res))

		return sel

	def get_infocuts(self, exclude="None", return_string=False):
		cutstring = "cuts= ("
		count=0
		if exclude is None:
			exclude=[]
		for i, name in enumerate(info_cuts):
			exc=False
			for ex in exclude:
				if ex in name:
					exc=True
			if not exc:
				if count>0:
					cutstring+= "& %s "%name
				else:
					cutstring+= "%s "%name
				print i, name
				count+=1
		cutstring+=")"
		print cutstring
		exec cutstring

		if not return_string:
			return cuts

		else:
			return cuts, cutstring.replace("self.res", "%s")

	def rotate(self, e1_new, e2_new):
		"""Rotate the ellipticities into a reference frame defined by another set of shapes. 
		   Generally this will probably be the PSF or nearest neighbour frame.
		"""

		e = e1_new + 1j*e2_new
		# Actually this is 2phi
		phi = np.angle(e)

		self.res["e1"] = self.res["e1"]*np.cos(phi) + self.res["e2"]*np.sin(phi)
		self.res["e2"] = -1*self.res["e1"]*np.sin(phi) + self.res["e2"]*np.cos(phi)
		self.res["mean_psf_e1_sky"] = self.res["mean_psf_e1_sky"]*np.cos(phi) + self.res["mean_psf_e2_sky"]*np.sin(phi)
		self.res["mean_psf_e2_sky"] = -1*self.res["mean_psf_e1_sky"]*np.sin(phi) + self.res["mean_psf_e2_sky"]*np.cos(phi)
		self.truth["intrinsic_e1"] = self.truth["intrinsic_e1"]*np.cos(phi) + self.truth["intrinsic_e2"]*np.sin(phi)
		self.truth["intrinsic_e2"] = -1*self.truth["intrinsic_e1"]*np.sin(phi) + self.truth["intrinsic_e2"]*np.cos(phi)
		self.truth["true_g1"] = self.truth["true_g1"]*np.cos(phi) + self.truth["true_g2"]*np.sin(phi)
		self.truth["true_g2"] = -1*self.truth["true_g1"]*np.sin(phi) + self.truth["true_g2"]*np.cos(phi)

	def apply_infocuts(self):
		n0 = len(self.res)
		inf = self.res["info_flag"]==0
		self.res = self.res[inf]
		if hasattr(self,"truth"):
			self.truth=self.truth[inf]
		if hasattr(self,"coadd"):
			self.coadd=self.coadd[inf]
		print "%d/%d (%f percent) survived info cuts."%(len(self.res), n0, 100.*len(self.res)/n0)
		return 0

	def get_neighbours(self):
		import copy
		from sklearn.neighbors import NearestNeighbors
		import scipy.spatial as sps

		fulltruth = di.load_truth(self.truth_path)

		import fitsio as fi
		reference=fi.FITS("/home/samuroff/y1a1_16tiles_positions.fits")[1].read()
		fulltruth,reference = di.match_results(fulltruth,reference, name1="coadd_objects_id", name2="DES_id")
		fulltruth["ra"]=reference["ra"]
		fulltruth["dec"]=reference["dec"]

		meds_path=self.truth_path.replace("truth", "meds/*/*")
		meds_info = di.get_pixel_cols(meds_path)
		pool_of_possible_neighbours,fulltruth = di.match_results(meds_info,fulltruth, name1="DES_id", name2="coadd_objects_id" )
		fulltruth = arr.add_col(fulltruth, "ix", pool_of_possible_neighbours["ix"])
		fulltruth = arr.add_col(fulltruth, "iy", pool_of_possible_neighbours["iy"])
		fulltruth = arr.add_col(fulltruth, "tile", pool_of_possible_neighbours["tile"])

		objects_needing_neighbours,self.truth = di.match_results(meds_info,self.truth, name1="DES_id", name2="coadd_objects_id" )
		self.truth = arr.add_col(self.truth, "ix", objects_needing_neighbours["ix"])
		self.truth = arr.add_col(self.truth, "iy", objects_needing_neighbours["iy"])
		self.truth = arr.add_col(self.truth, "tile", objects_needing_neighbours["tile"])



		cut=(fulltruth["sextractor_pixel_offset"]<1.0) & (fulltruth["ra"]!=0.0)
		fulltruth = fulltruth[cut]
		pool_of_possible_neighbours = pool_of_possible_neighbours[cut]

		indices = np.zeros(self.res.size)
		distances = np.zeros(self.res.size)
		lookup = np.linspace(0,fulltruth.size-1, fulltruth.size).astype(int)

		tiles = np.unique(self.truth["tile"]) 

		for it in tiles:
			print "Matching in pixel coordinates, tile %s"%it
			sel0 = pool_of_possible_neighbours["tile"]==it
			sel1 = objects_needing_neighbours["tile"]==it

			# All positions where an object was simulated
			# Restrict the search to this tile
			x_pool = pool_of_possible_neighbours["ix"][sel0]
			y_pool = pool_of_possible_neighbours["iy"][sel0]
			xy_pool=np.vstack((x_pool,y_pool))

			# Positions of those objects for which we have im3shape results
			# We want to find neighbours for these objects
			x_tar = self.truth["ix"][sel1]
			y_tar = self.truth["iy"][sel1]
			xy_tar=np.vstack((x_tar,y_tar))

			# Build a tree using the pool
			nbrs = NearestNeighbors(n_neighbors=2, algorithm='kd_tree', metric="euclidean").fit(xy_pool.T)
			# Query it for the target catalogue
			d,i = nbrs.kneighbors(xy_tar.T)
			distances[sel1], indices[sel1] = d.T[1], lookup[sel0][i.T[1]]

		neighbour_cat = copy.deepcopy(self)

		neighbour_cat.res["id"]= fulltruth[indices.astype(int)]["DES_id"]
		neighbour_cat.res["coadd_objects_id"]= fulltruth[indices.astype(int)]["DES_id"]
		neighbour_cat.res["e1"]= fulltruth[indices.astype(int)]["intrinsic_e1"]+fulltruth[indices.astype(int)]["true_g1"] 
		neighbour_cat.res["e2"]= fulltruth[indices.astype(int)]["intrinsic_e2"]+fulltruth[indices.astype(int)]["true_g2"]
		np.putmask(neighbour_cat.res["e1"], neighbour_cat.res["e1"]<-1, fulltruth[indices.astype(int)]["mean_psf_e1"])
		np.putmask(neighbour_cat.res["e2"], neighbour_cat.res["e2"]<-1, fulltruth[indices.astype(int)]["mean_psf_e2"])
		neighbour_cat.res["ra"]= fulltruth[indices.astype(int)]["ra"]
		neighbour_cat.res["dec"]= fulltruth[indices.astype(int)]["dec"]
		neighbour_cat.truth= fulltruth[indices.astype(int)]
		neighbour_cat.truth["nearest_neighbour_pixel_dist"] = distances

		return neighbour_cat

	def get_phi_col(self,neighbour_cat):
		print "Computing ellipticity-ellipticity misalignment between each object and its nearest neighbour."
		eres = self.res["e1"]+ 1j*self.res["e2"]
		eneigh = neighbour_cat.res["e1"] + 1j*neighbour_cat.res["e2"]

		phi_res = np.angle(eres)
		phi_neigh = np.angle(eneigh)
		dphi = (phi_res - phi_neigh)/2

		# Enforce limits at +-pi, then +-pi/2
		#sel1=dphi>np.pi
		#sel2=dphi<-1.0*np.pi
#
		#dphi[sel1] = -1.0*np.pi + (dphi[sel1]-np.pi)
		#dphi[sel2] = 1.0*np.pi + (dphi[sel2]+np.pi)

		sel1=dphi>np.pi/2
		sel2=dphi<-1.0*np.pi/2
		
		dphi[sel1] = np.pi/2 - (dphi[sel1] - np.pi/2)
		dphi[sel2] = -1.*np.pi/2 - (dphi[sel2] + np.pi/2)

		dphi/=np.pi

		self.res = arr.add_col(self.res,"dphi",dphi)

	def get_beta_col(self,ncat):
		print "Computing ellipticity-position misalignment angle between each object and its nearest neighbour."
		
		dx = self.truth["ra"] - ncat.truth["ra"]
		dy = self.truth["dec"] - ncat.truth["dec"]

		# position angle of the separation vector, in sky coordinates
		# has bounds [-pi,pi]
		theta = np.arctan(dy/dx)

		# position angle of the central galaxy in stamp coordinates
		eres = self.res["e1"]+ 1j*self.res["e2"]
		phi = np.angle(eres)/2



		# cos(beta) = Rneigh.ecent 
		# where Rneigh, ecent are unit vectors
		beta = (phi - theta)
		np.putmask(beta,np.invert(np.isfinite(beta)),0)

		# Impose bounds as above
		sel1=beta>np.pi/2
		sel2=beta<-1.0*np.pi/2
		beta[sel1] = np.pi/2 - (beta[sel1] - np.pi/2)
		beta[sel2] = -1.*np.pi/2 - (beta[sel2] + np.pi/2)

		beta/=np.pi

		self.res = arr.add_col(self.res,"dbeta",beta)

	def angle_cols(self, ncat):
		self.get_phi_col(ncat)
		self.get_beta_col(ncat)

	def get_2pt(self, corr1, corr2, nbins=12, error_type="bootstrap", xmin=1, xmax=300, units="arcmin"):
		correlation_lookup = {"psf":("mean_psf_e%d_sky", self.res), "gal":("e%d", self.res)}

		if hasattr(self,"truth"): correlation_lookup["int"] = ("intrinsic_e%d", self.truth)

		c1, data1 = correlation_lookup[corr1]
		c2, data2 = correlation_lookup[corr2]
		print "Will correlate columns %s and %s."%(c1,c2), 

		cat1 = tc.Catalog(ra=self.res["ra"]*60, dec=self.res["dec"]*60, ra_units=units, dec_units=units, g1=data1[c1%1], g2=data1[c1%2])
		cat2 = tc.Catalog(ra=self.res["ra"]*60, dec=self.res["dec"]*60, ra_units=units, dec_units=units, g1=data2[c2%1], g2=data2[c2%2])

		gg = tc.GGCorrelation(nbins=nbins, min_sep=xmin, max_sep=xmax, sep_units=units)

		gg.process(cat1,cat2)

		setattr(gg, "theta", np.exp(gg.logr))

		print "stored"
		self.corr[(corr1,corr2)]=gg

	def get_alpha_from_2pt(self):
		xi_pp = self.corr["psf","psf"].xip
		xi_gp = self.corr["gal","psf"].xip

		egal = self.res["e1"] + 1j*self.res["e2"]
		epsf = self.res["mean_psf_e1_sky"] + 1j*self.res["mean_psf_e2_sky"]

		alpha = ( xi_gp - np.mean(egal).conj()*np.mean(epsf) ) / ( xi_pp - abs(np.mean(epsf))*abs(np.mean(epsf)) )
		x = self.corr["psf","psf"].theta

		return x, alpha

	def get_fofz(self, nbins, error_type="bootstrap", zmax=1.8, binning="equal_number", T_B=False, return_number=False, split_type="im3shape", bin_type="mean_z_bpz"):
		"""Calculate the bulge fraction in bins using the given definition"""
		fr=[]
		e1=[]
		Tofz=[]
		bTofz=[]
		nofz_bulge=[]
		nofz_disc=[]

		if binning is "equal_number":
			bins = di.find_bin_edges(self.res[bin_type][self.res[bin_type]<zmax] , nbins)
		elif binning is "uniform":
			bins = np.linspace(0, zmax, nbins+1)

		for i, lower in enumerate(bins[:-1]):
			print i, 
			upper = bins[i+1]
			sel = (self.res[bin_type]>lower) & (self.res[bin_type]<upper)
			bulge_frac, selb = self.get_bulge_fraction(self.res[sel], split_type=split_type, return_mask=True)
			fr.append(bulge_frac)
			nofz_bulge.append(self.res[sel][selb].size)
			nofz_disc.append(self.res[sel][np.invert(selb)].size)

			if error_type is "bootstrap":
				e1.append(di.bootstrap_error(50, self.res[sel], self.get_bulge_fraction, additional_args=["split_type", "return_mask"], additional_argvals=[split_type, False]))
			else:
				e1.append(1.0 / np.sqrt(self.res[(sel)].shape[0]) )

			if T_B:
				Tofz.append(np.mean(self.res[(sel)]["T_B"]))
				bTofz.append(np.mean(self.res[(sel)]["T_B"]))

		z = (bins[1:]+bins[:-1])/2
		if T_B:
			out = (z, np.array(fr), np.array(e1), np.array(Tofz), np.array(bTofz))
		if return_number:
			out=(z,np.array(fr), np.array(e1), [nofz_disc, nofz_bulge])
		else:
			out = (z, np.array(fr), np.array(e1))

		return out


info_cuts =["(self.res['fails_unmasked_flux_frac']==0)", "(self.res['snr']>10)", "(self.res['snr']<10000)", "(self.res['mean_rgpp_rp']>1.1)", "(self.res['mean_rgpp_rp']<3.5)", "(self.res['radius']<5)", "(self.res['radius']>0.1)", "((self.res['ra_as']**2+self.res['dec_as']**2)**0.5<1.0)", "(self.res['chi2_pixel']>0.5)", "(self.res['chi2_pixel']<1.5)", "(self.res['min_residuals']>-0.2)", "(self.res['max_residuals']<0.2)", "(self.res['mean_psf_fwhm']<7.0)", "(self.res['mean_psf_fwhm']>0.0)", "(self.res['error_flag']==0)"]

class blank_stamp:
	def __init__(self, boxsize):
		self.array = np.zeros((boxsize,boxsize))

class dummy_im3shape_options():
	def __init__(self):
		self.psfex_rerun_version="y1a1-v02"
		self.verbosity=2
		rescale_stamp = "Y"
		self.upsampling = 5
		self.n_central_pixel_upsampling = 4
		self.n_central_pixels_to_upsample = 5
		self.padding = 4
		self.stamp_size = 48
		self.psf_input = "bundled-psfex"

class meds_wrapper(i3meds.I3MEDS):
	def __init__(self, filename, update=False):
		super(meds_wrapper, self).__init__(filename)
		setattr(self, "filename", self._filename)

		if update:
			self._fits.close()
			print "Beware: FITS file can be overwritten in update mode."
			self._fits = fitsio.FITS(filename, "rw")

		self.setup_dummy_im3shape_options()

	def setup_dummy_im3shape_options(self):
		self.options = dummy_im3shape_options()
		
	def _get_extension_name(self, type):
		"""
		    Extended version of the function in meds.py.
		    Now can be used to get simulation specific cutouts.
		"""
		if type=='image':
			return "image_cutouts"
		elif type=="weight":
			return "weight_cutouts"
		elif type=="seg":
			return "seg_cutouts"
		elif type=="bmask":
			return "bmask_cutouts"
		elif type=="model":
			return "model_cutouts"
		elif type=="noise":
			return "noise_cutouts"
		else: raise ValueError("bad cutout type '%s'" % type)

	def remove_noise(self, silent=False, outdir="noisefree"):
		p0 = self._fits["image_cutouts"].read()
		real = self._fits["model_cutouts"]
		noise = self._fits["noise_cutouts"]

		if not silent:
			print "will remove noise"

		for iobj, object_id in enumerate(self._cat["id"]):
			if not silent:
				print iobj, object_id
			# Find the relevant index range for this object
			i0 = self._cat["start_row"][iobj][0]
			i1 = self._cat["start_row"][iobj][0]+self._cat["box_size"][iobj]*self._cat["box_size"][iobj]*self._cat["ncutout"][iobj]

			# COSMOS profile + neighbours
			pixels = p0[i0:i1] - noise[i0:i1]
			pixels*=p0[i0:i1].astype(bool).astype(int)
			p0[i0:i1] = pixels

		print "Writing to MEDS file"
		self.clone(data=p0, colname="image_cutouts", newdir=outdir)

		return 0


	def remove_neighbours(self, silent=False, outdir="neighbourfree"):
		p0 = self._fits["image_cutouts"].read()
		real = self._fits["model_cutouts"]
		noise = self._fits["noise_cutouts"]

		if not silent:
			print "will remove neighbours"

		for iobj, object_id in enumerate(self._cat["id"]):
			if not silent:
				print iobj, object_id
			# Find the relevant index range for this object
			i0 = self._cat["start_row"][iobj][0]
			i1 = self._cat["start_row"][iobj][0]+self._cat["box_size"][iobj]*self._cat["box_size"][iobj]*self._cat["ncutout"][iobj]

			# COSMOS profile + noise
			neighbours = p0[i0:i1]- real[i0:i1] - noise[i0:i1]
			pixels = p0[i0:i1] - neighbours
			pixels *= p0[i0:i1].astype(bool).astype(int)
			p0[i0:i1] = pixels

		print "Writing to MEDS file"
		self.clone(data=p0, colname="image_cutouts", newdir=outdir)

		return 0

	def remove_model_bias(self, shapecat, silent=False, outdir="analytic"):
		p0 = self._fits["image_cutouts"].read()
		real = self._fits["model_cutouts"]

		if not silent:
			print "will insert analytic profiles"

		if not hasattr(shapecat, "res"):
			setattr(shapecat, "res", shapecat.truth)

		for iobj, object_id in enumerate(self._cat["id"]):
			if not silent:
				print iobj, object_id
			# Find the relevant index range for this object
			i0 = self._cat["start_row"][iobj][0]
			i1 = self._cat["start_row"][iobj][0]+self._cat["box_size"][iobj]*self._cat["box_size"][iobj]*self._cat["ncutout"][iobj]

			# First subtract off the input profile flux
			existing = real[i0:i1]
			
			pixels = p0[i0:i1]-existing
			pixels*=p0[i0:i1].astype(bool).astype(int)

			icat = np.argwhere(shapecat.res["id"]==object_id)
			if len(icat)>0:
				icat=icat[0,0]
				res = shapecat.res[icat]
			else:
				print "Warning: no im3shape results found for object."
				res = np.random.choice(shapecat.res)
				icat = np.argwhere(shapecat.res["id"]==res["id"])[0,0]

			if hasattr(shapecat, "truth"):
				truth= shapecat.truth[icat]

			gal = self.construct_analytic_profile(res, shapecat.fit, truth=truth)
			stack = self.make_stack(gal,iobj)

			# noise + neighbours + analytic profile
			try:
				pixels+=stack
			except:
				import pdb ; pdb.set_trace()

			p0[i0:i1] = stack

		print "Writing to MEDS file"
		self.clone(data=p0, colname="image_cutouts", newdir=outdir)

		return 0

	def clone(self, data=None, colname="image_cutouts", newdir=None):
		out=fitsio.FITS("%s/%s"%(newdir,self._filename.replace(".fz","")), "rw")

		for j, h in enumerate(self._fits[1:]):
			hdr=h.read_header()
			extname=hdr["extname"]
			if extname in ["model_cutouts", "noise_cutouts"]:
				extname
			print extname
			if (data is not None) and extname==colname:
				print "new data in HDU %s"%colname
				dat = data
			else:
				dat=h.read()
			out.write(dat, header=hdr)
			out[-1].write_key('EXTNAME', extname)

		out.close()

	def make_stack(self,profile,iobj):
		boxsize = self._cat["box_size"][iobj]
		nexp = self._cat["ncutout"][iobj]

		stack = [np.zeros(boxsize*boxsize)]

		for iexp in xrange(1,nexp):
			wcs, offset = self.get_wcs(iobj,iexp)

			# Get the relevant zero point magnitude scaling
			i_image = self._cat["file_id"][iobj][iexp]
			magzp = self._image_info[i_image]["magzp"]
			rf = 10**( (magzp - 30) / 2.5 )

			psf = self.get_bundled_psfex_psf(iobj, iexp, self.options, return_profile=True)

			if (profile is not None) and (psf is not None):
				final = galsim.Convolve([profile,psf]) * rf
			elif profile is None:
				final = psf
			elif psf is None:
				final = profile
			
			if final is not None:	
				stamp = final.drawImage(wcs=wcs, nx=boxsize, ny=boxsize, method='no_pixel',offset=offset)
			else:
				stamp=blank_stamp(boxsize)

			stack.append(stamp.array.flatten())

		return np.concatenate(stack)

	def get_bundled_psfex_psf(self, iobj, iexp, options, return_profile=False):

		wcs_path = self.get_source_info(iobj,iexp)[3].strip()

		wcs_path = check_wcs(wcs_path)

		#Find the exposure name
		source_path = self.get_source_path(iobj, iexp)
		source = os.path.split(source_path)[1].split('.')[0]

		#PSF blacklist
		if source in self.blacklist:
			if options.verbosity>2:
				print "%s blacklisted" % source
			return None

		#get the HDU name corresponding to that name.
		#Might need to tweak that naming
		hdu_name = "psf_"+options.psfex_rerun_version+"_"+source+"_psfcat"

		#Maybe we have it in the cache already
		if hdu_name in PSFEX_CACHE:
			psfex_i = PSFEX_CACHE[hdu_name]
			if psfex_i is None:
				return None

		else:
    		#Turn the HDU into a PSFEx object
    		#PSFEx expects a pyfits HDU not fitsio.
    		#This is insane.  I know this.
			import galsim.des
			try:
				pyfits = galsim.pyfits
			except AttributeError:
				from galsim._pyfits import pyfits

			try:
				hdu = pyfits.open(self._filename)[hdu_name]
			except KeyError:
				PSFEX_CACHE[hdu_name] = None
				if options.verbosity>3:
					print "Could not find HDU %s in %s" % (hdu_name, self._filename)

				return None

			try:
				psfex_i = galsim.des.DES_PSFEx(hdu, wcs_path)
			except IOError:
				print "PSF bad but not blacklisted: %s in %s"%(hdu_name, self._filename)
				psfex_i = None

			PSFEX_CACHE[hdu_name] = psfex_i

		if psfex_i == None:
			return None

		#Get the image array
		return self.extract_psfex_psf(psfex_i, iobj, iexp, options, return_profile=return_profile)



	def extract_psfex_psf(self, psfex_i, iobj, iexp, options, return_profile=False):
		psf_size=(options.stamp_size+options.padding)*options.upsampling
		orig_col = self['orig_col'][iobj][iexp]
		orig_row = self['orig_row'][iobj][iexp]

		x_image_galsim = orig_col+1
		y_image_galsim = orig_row+1


		psf = psfex_i.getPSF(galsim.PositionD(x_image_galsim, y_image_galsim))

		image = galsim.ImageD(psf_size, psf_size)
		#psf.drawImage(image, scale=1.0/self.options.upsampling, offset=None, method='no_pixel')

		if return_profile:
			return psf

	def get_wcs(self, iobj, iexp):

		wcs_path = self.get_source_path(iobj, iexp)

		wcs_path = check_wcs(wcs_path)

		orig_col = self['orig_col'][iobj][iexp]
		orig_row = self['orig_row'][iobj][iexp]        
		image_pos = galsim.PositionD(orig_col,orig_row)
		wcs = galsim.FitsWCS(wcs_path)

		ix = int(math.floor(image_pos.x ))
		iy = int(math.floor(image_pos.y ))

		# Offset of the galaxy centroid from the stamp centre
		offset = (image_pos - galsim.PositionD(ix,iy))
		offset= galsim.PositionD(offset.x+0.5, offset.y+0.5)

		return wcs.local(image_pos), offset


	def construct_analytic_profile(self, res, fittype, truth=None):
		if fittype in sersic_indices.keys():
			n = sersic_indices[fittype]
		elif fittype=="bord":
			n = 1 + res["is_bulge"].astype(int)*3
			fittype = {4: "bulge", 1: "disc"} [n] 

		if truth is not None:
			e1 = truth["intrinsic_e1"]
			e2 = truth["intrinsic_e2"]
			g1 = truth["true_g1"]
			g2 = truth["true_g2"]
			hlr = truth["hlr"]
			flux = truth["flux"]

			if (g1==-9999.) or (g2==-9999.):
				return None
		else:
			e1 = res["e1"][0,0]
			e2 = res["e2"][0,0]
			g1 = 0
			g2 = 0
			flux = res["%s_flux"%fittype][0,0]

		gal=galsim.Sersic(n=n,half_light_radius=hlr)

		gal=gal.withFlux(flux)

		e1 += g1
		e2 += g2
		if e1>1: e1=1
		if e1<-1: e1=-1
		if e2>1: e2=1
		if e2<-1: e2=-1

		try:
			shear = galsim.Shear(g1=e1, g2=e2)
			print "applying shear g1=%1.3f,g2=%1.3f"%(e1,e2)
		except:
			print "ERROR: unphysical shear"
			shear= galsim.Shear(g1=0, g2=0)

		gal.shear(shear)

		return gal

	def download_source_images(self, coadd=False, red=True):
		
		for iobj, object_id in enumerate(self._cat["id"]):
			nexp = self._cat["ncutout"][iobj]
			i0 = 0
			i1 = nexp
			if not coadd:
				i0+=1
			if not red:
				i1=0

			for iexp in xrange(i0,i1):
				file_id = self._cat["file_id"][iobj, iexp]
				path = self._image_info["image_path"][file_id].strip()
				path = check_wcs(path,iexp)



def check_wcs(wcs_path, iexp=-9999):
	if not os.path.exists(wcs_path):
		wcs_path = "/share/des/disc3/samuroff/y1/data/OPS/"+wcs_path.split("OPS")[-1].strip()
		if iexp==0:
			wcs_path=wcs_path.replace(".fz","")

	if not os.path.exists(wcs_path):
		print "Warning. Could not find WCS, so will download it to %s."%wcs_path
		print "Are you sure this is what you want to do?"
		source = wcs_path.replace("/share/des/disc3/samuroff/y1/data/OPS/", "/global/cscratch1/sd/sws/data/OPS/")
		os.system("mkdir -p %s"%os.path.dirname(wcs_path))
		os.system("scp sws@edison.nersc.gov:%s %s"%(source,os.path.dirname(wcs_path)))

	return wcs_path




#& (self.res['chi2_pixel']>0.5) &



def add_col(rec, name, arr=[], dtype=None):
	"""Generic function to add a new column to a structured numpy array.
	Borrows heavily from Tomek's code."""

	if len(arr)==0:
		arr=np.zeros(len(rec))

	arr = np.asarray(arr)
	if dtype is None:
		dtype = arr.dtype

	newdtype = np.dtype(rec.dtype.descr + [(name, dtype)])
	newrec = np.empty(rec.shape, dtype=newdtype)
	for field in rec.dtype.fields:
		newrec[field] = rec[field]

	newrec[name] = arr

	return newrec

def split_by(array, column_name, pivot, return_mask=False, logger=None):
	"""Return halves of a structured array split about a given value in one of the columns."""

	lower= array[(array[column_name]<pivot)]
	upper= array[(array[column_name]>pivot)]

	f = 1.0*len(upper)/len(array)

	if logger is not None:
		logger.info("Splitting array about %s=%3.4f (%3.2f percent above)"%(column_name,pivot, f*100.))

	if return_mask:
		return f, (array[column_name]<pivot)

	else:
		return f, upper, lower
