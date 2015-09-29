from cosmosis.datablock import names, option_section
from luminosity_function import jb_calculate_alpha
import luminosity_function as luminosity
import numpy as np
import pdb

def setup(options):
	#method = options[option_section, "method"].lower()
	# For the moment we only have one method. It may or may not be useful to try implementing more here later. 
	#if method not in ["jb"]:
	#	raise ValueError('The method in the luminosity function module must'
	#		'be either "JB" (Joachimi and Bridle 2010) or')
	
	survey = options[option_section, "survey"]
	try:	binned_alpha = options[option_section, "binned_alpha"]
	except:	binned_alpha = True

	return (survey, binned_alpha )

def execute(block, config):
	ia = names.intrinsic_alignment_parameters
	cos = names.cosmological_parameters
	lum = names.galaxy_luminosity_function 
	
	survey, use_binned_alpha = config 

	mag_lim = block.get_double(survey, 'magnitude_limit')

	# Obtain the fine grid points and limits for the redshift from the datablock
	# If the information isn't there already, set these parameters to sensible values
	try: Nz = int(block[survey, 'nz']) ;
	except: Nz = 500
	nzbin = int(block[survey, 'nzbin'])
	zmax = block[survey, 'edge_%d'%(nzbin+1)]		 

	coeff_a = luminosity.initialise_jb_coefficients(mag_lim)
	alpha , z = jb_calculate_alpha(coeff_a, zmax, Nz)	

	# Write the fine grid alpha to the datablock
	try: block.put_double_array_1d(lum,'alpha',alpha)
	except: pdb.set_trace()
	block.put_double_array_1d(lum,'z',z)	

	# If required then interpolate alpha(z,rlim) to the mean values in each of the specified redshift bins
	if use_binned_alpha:
		alpha_bin, z_bar = luminosity.get_binned_alpha(block, survey, alpha, z)
	
		# Then write these to the datablock
		block.put_double_array_1d(lum, 'alpha_binned', alpha_bin)
		block.put_double_array_1d(lum, 'z_binned', z_bar)
		
	return 0

def cleanup(config):
	pass
