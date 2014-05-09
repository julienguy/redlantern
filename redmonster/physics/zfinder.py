import numpy as n
from os import environ
from os.path import join, exists
from redmonster.datamgr.ssp_prep import SSP_Prep
from redmonster.math.misc import poly_array, two_pad
from time import gmtime, strftime
from astropy.io import fits
from redmonster.datamgr.io import read_ndArch

import matplotlib as m
from matplotlib import pyplot as p

class Zfinder:
    
    def __init__(self, fname=None, config=None, npoly=None, zmin=None, zmax=None):
        self.fname = fname
        self.config = config
        self.npoly = npoly if npoly else 3
        self.zmin = zmin
        self.zmax = zmax
        try: self.specdir = environ['IDLSPEC2D_DIR']
        except: self.specdir = None
        if self.config.lower() == 'ssp': self.set_SSP(npoly=npoly)
        if self.config.lower() == 'ssptest': self.set_SSP_test(npoly=npoly)
        if self.config.lower() == 'star': self.set_star(npoly=npoly)
        #self.read_template()
        self.npars = len(self.templates.shape) - 1
        self.templates_flat = n.reshape(self.templates, (-1,self.fftnaxis1))
        self.t_fft = n.fft.fft(self.templates_flat)
        self.t2_fft = n.fft.fft(self.templates_flat**2)

    def read_template(self):
        self.templates, self.baselines, self.infodict = read_ndArch(self.fname)
        self.origshape = self.templates.shape
        self.ntemps = self.templates[...,0].size
        self.fftnaxis1 = two_pad(self.origshape[-1])
        self.tempwave = self.infodict['coeff0'] + n.arange(self.infodict['nwave'])*self.infodict['coeff1']
        templates_pad = n.zeros( self.origshape[:-1]+(self.fftnaxis1,) )
        templates_pad[...,:self.origshape[-1]] = self.templates
        self.templates = templates_pad
    
    def set_SSP(self, npoly=None):
        ssp_stuff = SSP_Prep(velmin=100, velstep=100, nvel=3) # THIS MAY NOT BE THE BEST WAY TO DO THIS
        self.templates, self.tempwave, self.coeff1 = ssp_stuff.specs, ssp_stuff.wave, ssp_stuff.coeff1
    
    def set_SSP_test(self, npoly=None): # FOR TESTING - Skips SSP processing and just reads from templates.fits to speed things up
        hdu = fits.open('/Users/Tim/Documents/Workstuff/BOSS/Python/templates.fits')
        self.templates = hdu[0].data
        self.tempwave = hdu[1].data.LAMBDA
        self.origshape = self.templates.shape
        self.ntemps = n.prod(self.templates.shape[:-1])
        self.fftnaxis1 = two_pad(self.origshape[-1])
        templates_pad = n.zeros( self.origshape[:-1] + (self.fftnaxis1,))
        templates_pad[...,:self.origshape[-1]] = self.templates
        self.templates = templates_pad
    
    def set_star(self, npoly=None):
        hdu = fits.open('/Applications/itt/idl70/lib/idlspec2d-v5_6_4/templates/spEigenStar-55734.fits')
        self.templates = hdu[0].data
        self.tempwave = 10**(hdu[0].header['COEFF0'] + hdu[0].header['COEFF1']*n.arange(hdu[0].header['NAXIS1']))
        self.origshape = self.templates.shape
        self.fftnaxis1 = two_pad(self.origshape[-1])
        templates_pad = n.zeros( self.origshape[:-1] + (self.fftnaxis1,))
        templates_pad[...,:self.origshape[-1]] = self.templates
        self.templates = templates_pad
        self.hdr = hdu[0].header
    
    def create_z_baseline(self, loglam0):
        self.zbase = ((10**loglam0)/self.tempwave) - 1
    
    def zchi2(self, specs, specloglam, ivar):
        print strftime("%Y-%m-%d %H:%M:%S", gmtime()) # For timing while testing
        num_z = self.templates.shape[-1] - specs.shape[-1] + 1 # Number of pixels to be fitted in redshift
        shape = (specs.shape[0],) + self.templates.shape[:-1] + (num_z,)
        #fftnaxis1 = 2**13 if self.templates.shape[-1] <= 2**13 else 2**14

        # Create arrays for use in routine
        zchi2arr = n.zeros(shape) # Create chi2 array of shape (# of fibers, template_parameter_1, ... , template_parameter_N, # of redshifts)
        polyarr = poly_array(self.npoly, specs.shape[1]) # Compute poly terms, noting that they will stay fixed with the data - assumes data is passed in as shape (nfibers, npix)
        pmat = n.zeros( (self.npoly+1, self.npoly+1, fftnaxis1), dtype=float)
        bvec = n.zeros( (self.npoly+1, self.fftnaxis1), dtype=float)
        
        # Pad data and SSPs to a power of 2 for faster FFTs
        temp_pad = n.zeros(self.templates.shape[:-1] + (self.fftnaxis1,), dtype=float)
        temp_pad[...,:self.templates.shape[-1]] = self.templates
        data_pad = n.zeros(specs.shape[:-1] + (self.fftnaxis1,), dtype=float)
        data_pad[...,:specs.shape[-1]] = specs
        ivar_pad = n.zeros(ivar.shape[:-1] + (self.fftnaxis1,), dtype=float)
        ivar_pad[...,:specs.shape[-1]] = ivar
        poly_pad = n.zeros((self.npoly, self.fftnaxis1), dtype=float)
        poly_pad[...,:polyarr.shape[-1]] = polyarr
        
        # Pre-compute FFTs for use in convolutions
        t_fft = n.fft.fft(temp_pad)
        t2_fft = n.fft.fft(temp_pad**2)
        data_fft = n.fft.fft(data_pad * ivar_pad)
        ivar_fft = n.fft.fft(ivar_pad)
        poly_fft = n.zeros((ivar_pad.shape[0], self.npoly, self.fftnaxis1), dtype=complex)
        for i in xrange(self.npoly):
            poly_fft[:,i,:] = n.fft.fft(poly_pad[i] * ivar_pad)
        
        # Compute z for all fibers
        #import pdb; pdb.set_trace()
        for i in xrange(specs.shape[0]): # Loop over fibers
            #bvec[1:,:] = n.sum( poly_pad * data_pad[i] * ivar_pad[i], axis=1)
            #import pdb; pdb.set_trace()
            for ipos in xrange(self.npoly): bvec[ipos+1] = n.sum( poly_pad[ipos] * data_pad[i] * ivar_pad[i])
            sn_data = n.sum( (specs[i]**2)*ivar[i] )
            for ipos in xrange(self.npoly):
                for jpos in xrange(self.npoly): pmat[ipos+1,jpos+1] = n.sum( poly_pad[ipos] * poly_pad[jpos] * ivar_pad[i])
            for j in xrange(self.templates.shape[0]): # Loop over template_param1
                for k in xrange(self.templates.shape[1]): # Loop over template_param2
                    pmat[0,0] = n.fft.ifft(t2_fft[j,k] * ivar_fft[i].conj()).real
                    bvec[0] = n.fft.ifft(t_fft[j,k] * data_fft[i].conj()).real
                    for ipos in xrange(self.npoly): pmat[ipos+1,0] = pmat[0,ipos+1] = n.fft.ifft(t_fft[j,k] * poly_fft[i,ipos].conj()).real
                    for l in range(num_z): # Solve pmat.f = bvec at all pixel-redshifts l and compute chi2 at those redshifts
                        f = n.linalg.solve(pmat[:,:,l],bvec[:,l])
                        zchi2arr[i,j,k,l] = sn_data - n.dot(n.dot(f,pmat[:,:,l]),f)
        print strftime("%Y-%m-%d %H:%M:%S", gmtime()) # For timing while testing
        bestl = n.where(zchi2arr == n.min(zchi2arr))[3][0]
        thisz = ((10**(specloglam[0]))/self.tempwave[bestl])-1
        print thisz
        return zchi2arr

    def zchi3(self, specs, specloglam, ivar):
        print strftime("%Y-%m-%d %H:%M:%S", gmtime()) # For timing while testing
        self.create_z_baseline(specloglam[0])
        num_z = self.origshape[-1] - specs.shape[-1] + 1 # Number of pixels to be fitted in redshift
        
        # Create arrays for use in routine
        zchi2arr = n.zeros((specs.shape[0], self.templates_flat.shape[0], num_z)) # Create chi2 array of shape (# of fibers, template_parameter_1, ... , template_parameter_N, # of redshifts)
        polyarr = poly_array(self.npoly, specs.shape[1]) # Compute poly terms, noting that they will stay fixed with the data - assumes data is passed in as shape (nfibers, npix)
        pmat = n.zeros( (self.npoly+1, self.npoly+1, self.fftnaxis1), dtype=float)
        bvec = n.zeros( (self.npoly+1, self.fftnaxis1), dtype=float)
        
        # Pad data and SSPs to a power of 2 for faster FFTs
        data_pad = n.zeros(specs.shape[:-1] + (self.fftnaxis1,), dtype=float)
        data_pad[...,:specs.shape[-1]] = specs
        ivar_pad = n.zeros(ivar.shape[:-1] + (self.fftnaxis1,), dtype=float)
        ivar_pad[...,:specs.shape[-1]] = ivar
        poly_pad = n.zeros((self.npoly, self.fftnaxis1), dtype=float)
        poly_pad[...,:polyarr.shape[-1]] = polyarr
        
        # Pre-compute FFTs for use in convolutions
        data_fft = n.fft.fft(data_pad * ivar_pad)
        ivar_fft = n.fft.fft(ivar_pad)
        poly_fft = n.zeros((ivar_pad.shape[0], self.npoly, self.fftnaxis1), dtype=complex)
        for i in xrange(self.npoly):
            poly_fft[:,i,:] = n.fft.fft(poly_pad[i] * ivar_pad)
        
        # Compute z for all fibers
        for i in xrange(specs.shape[0]): # Loop over fibers
            for ipos in xrange(self.npoly): bvec[ipos+1] = n.sum( poly_pad[ipos] * data_pad[i] * ivar_pad[i])
            sn2_data = n.sum( (specs[i]**2)*ivar[i] )
            for ipos in xrange(self.npoly):
                for jpos in xrange(self.npoly): pmat[ipos+1,jpos+1] = n.sum( poly_pad[ipos] * poly_pad[jpos] * ivar_pad[i])
            for j in xrange(self.templates_flat.shape[0]): # Loop over templates
                pmat[0,0] = n.fft.ifft(self.t2_fft[j] * ivar_fft[i].conj()).real
                bvec[0] = n.fft.ifft(self.t_fft[j] * data_fft[i].conj()).real
                for ipos in xrange(self.npoly): pmat[ipos+1,0] = pmat[0,ipos+1] = n.fft.ifft(self.t_fft[j] * poly_fft[i,ipos].conj()).real
                for l in range(num_z): # Solve pmat.f = bvec at all pixel-redshifts l and compute chi2 at those redshifts
                    f = n.linalg.solve(pmat[:,:,l],bvec[:,l])
                    zchi2arr[i,j,l] = sn2_data - n.dot(n.dot(f,pmat[:,:,l]),f)
        print strftime("%Y-%m-%d %H:%M:%S", gmtime()) # For timing while testing
        if self.config == 'star':
            besttemp = n.where(zchi2arr == n.min(zchi2arr))[1][0]
            print 'TYPE: ' + self.hdr['NAME%s' % besttemp]
        zchi2arr = n.reshape(zchi2arr, (specs.shape[0],) + self.origshape[:-1] + (num_z,) )
        bestl = n.where(zchi2arr == n.min(zchi2arr))[-1][0]
        thisz = ((10**(specloglam[0]))/self.tempwave[bestl])-1
        print thisz
        return zchi2arr













