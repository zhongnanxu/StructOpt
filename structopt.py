# Copyright (C) 2016 - Zhongnan Xu
'''This contains the mast_structopt class calculator for running structopt through MAST. Outside of running calculations, this file contains functions for organizing, reading, and writing data'''

import os
import commands
import shutil
from string import split, strip
import json
from subprocess import Popen, PIPE

from ase.calculators.general import Calculator
from ase.atoms import Atoms, Atom

from structopt_rc import *
from structopt_exceptions import *

class Structopt(Calculator):
    '''This is an ase.calculator class that allows the use of structopt
    and mast through ase'''

    def __init__(self, calcdir=None, **kwargs):
        if calcdir==None:
            self.calcdir = os.getcwd()
        else:
            self.calcdir = os.path.expanduser(calcdir)
        self.system_name = os.path.basename(self.calcdir)
        self.cwd = os.getcwd()
        self.kwargs = kwargs

        # If we are not using the context manager, then we have to
        # initialize the atoms. If we are, __enter__ will evaluate
        # and atoms are initialized there.
        if calcdir==None:
            self.initialize(**self.kwargs)

    def __enter__(self):
        '''On enter, make sure directory exists. Create it if necessary
        and change into the directory. Then return the calculator.'''

        # Make directory if it doesn't already exist
        if not os.path.isdir(self.calcdir):
            os.makedirs(self.calcdir)

        # Now change into the new working directory
        os.chdir(self.calcdir)
        self.initialize(**self.kwargs)

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        '''On exit, change back to the original directory'''

        os.chdir(self.cwd)

        return

    def initialize(self, **kwargs):
        '''We need an extra initialize because things are only done once
        we are inside the directory. The objectives of this function are...

        1. Set some additional run paramaters. These parameters are kept
        different because we don't want them initializing another run

        2. Get the status of the calculation. Generally, these fall into
        clean, running, finished, error. If it is not clean, it should
        read the input file and store them. 

        3. Set the new kwargs (if they are new).'''

        self.structopt_params = {}
        self.stem_params = {}
        self.lammps_params = {}
        
        for key in structopt_keys:
            self.structopt_params[key] = None
        for key in stem_keys:
            self.stem_params[key] = None
        for key in lammps_keys:
            self.lammps_params[key] = None

        self.run_params = {'nodes': 1,
                           'walltime': 24,
                           'ppn': None,
                           'queue': None,
                           'mpirun': 'mpirun',
                           'python': 'python',
                           'qsys': 'pbs'}
        
        
        # Now we go through logic to see what to do
        # First check if this is clean directory
        if not os.path.exists('structopt_inp.json'):
            self.structopt_running = False
            self.converged = False
            self.status = 'empty'

        # If there's only an input file and never got submitted
        elif (os.path.exists('structopt_inp.json')
              and not os.path.exists('jobid')):
            self.read_input()
            self.structopt_running = False
            self.converged = False
            self.status = 'empty'

        # If it is running or queued
        elif (os.path.exists('structopt_inp.json')
              and os.path.exists('jobid')
              and self.job_in_queue()):
            self.read_input()
            self.structopt_running = False
            self.converged = False
            self.status = 'running'
        

        # If job is done and this is our first time looking at it
        elif (os.path.exists('structopt_inp.inp')
              and os.path.exists('jobid')
              and not self.job_in_queue()
              and os.path.exists('out.txt')):
            self.read_input()
            self.read_output()
            os.unlink('jobid')
            self.status = 'done'

        # If the job is done we're looking at it again
        elif (os.path.exists('structopt_inp.inp')
              and not os.path.exists('jobid')
              and os.path.exists('out.txt')):
            self.read_input()
            self.read_output()
            self.status = 'done'

        # We want to alert the user of weird directories
        else:
            raise StructoptUnknownState

        # Store the old parameters read from files for restart purposes
        self.old_structopt_params = self.structopt_params.copy()
        self.old_lammps_params = self.lammps_params.copy()
        self.old_stem_params = self.stem_params.copy()        

        # We first set the default keys. Then we set the ones custom
        self.set(**kwargs)

        # Set the ppn automatically if not specified
        if self.run_params['ppn'] == None:
            self.run_params['ppn'] = self.set_ppn()

        return

    def set_ppn(self):
        '''The purpose of this function is to automatically set the ppn
        depending on which queue we ask for'''
        
        queue = self.run_params['queue']
        if queue == 'morgan1':
            return 8
        elif queue in ['morgan.q', 'morgan2', 'morganeth.q']:
            return 12
        elif queue == 'morgan3':
            return 32
        else:
            raise ValueError('Queue not found: ' + queue)            

    def job_in_queue(self, jobid='jobid'):
        '''return True or False if the directory has a job in the queue'''
        if not os.path.exists(jobid):
            return False
        else:
            # get the jobid
            jobid = open(jobid).readline().split()[-1]

            # Behavior will depend on whether we are in the slurm or pbs environment
            if self.run_params['qsys'] == 'pbs':
                jobids_in_queue = commands.getoutput('qselect').split('\n')
            else:
                jobids_in_queue = commands.getoutput('squeue -h -o %A').split('\n')

            if jobid in jobids_in_queue:
                # get details on specific jobid
                status, output = commands.getstatusoutput('qstat %s' % jobid)
                if status == 0:
                    lines = output.split('\n')
                    fields = lines[-1].split()
                    job_status = fields[4]
                    if job_status == 'C':
                        return False
                    else:
                        return True
            else:
                return False

    def job_finished(self):
        '''This function checks if the job is finished. This happens when
        there exists a jobdir file in the self.calcdir, there is no 
        corresponding file in SCRATCH_dir, and it exists in ARCHIVE_dir'''

        ARCHIVE_dir = os.environ['MAST_ARCHIVE'] + '/'
        if not hasattr(self, 'jobdir'):
            with open('jobdir', 'r') as f:
                self.jobdir = f.readline()
        if os.path.exists(ARCHIVE_dir + self.jobdir):
            return True
        else:
            return False

    def clean_output(self):
        '''This cleans out the output of large files'''
        
        f_dir = 'Output-rank0'.format(self.system_name, filename)
        rm_dirs = ['{0}/Restart-files'.format(f_dir),
                   '{0}/LAMMPSFiles'.format(f_dir)]
        for d in rm_dirs:
            if os.path.exists(d):
                shutil.rmtree(d)

        return

    def read_output(self):
        '''Figures out whether the calculation converged '''
        
        maxgen = self.int_params['maxgen']
        filename = self.string_params['filename']
        name = '{0}/{1}-rank0/Summary-{1}.txt'
        with open(name.format(self.system_name, filename), 'r') as f:
            lines = f.readlines()
            gen = int(lines[-1].split()[0])

        gens, fmins, favgs, fmeds, fmaxs, fstds = [], [], [], [], [], []
        gen_start = False
        for line in lines:
            if line.lower().startswith('generation'):
                gen_start = True
                continue
            if gen_start == False:
                continue
            gens.append(int(line.split()[0]))
            fmins.append(float(line.split()[1]))
            favgs.append(float(line.split()[2]))
            fmeds.append(float(line.split()[3]))
            fmaxs.append(float(line.split()[4]))
            fstds.append(float(line.split()[5]))
            
        self.gens = gens
        self.fmins = fmins
        self.favgs = favgs
        self.fmeds = fmeds
        self.fmaxs = fmaxs
        self.fstds = fstds

        if maxgen == gen:
            self.converged = False
        else:
            self.converged = True

        return

    def set(self, **kwargs):
        '''This function sets the keywords given a dictionary. It overwrites
        values that are different'''

        for key in kwargs:
            if key == 'parallel':
                self.structopt_params[key] = kwargs[key]
                self.lammps_params[key] = kwargs[key]
            if key == 'keep_files':
                self.stem_params[key] = kwargs[key]
                self.lammps_params[key] = kwargs[key]                
            elif self.structopt_params.has_key(key):
                self.structopt_params[key] = kwargs[key]
            elif self.stem_params.has_key(key):
                self.stem_params[key] = kwargs[key]
            elif self.lammps_params.has_key(key):
                self.lammps_params[key] = kwargs[key]
            elif self.run_params.has_key(key):
                self.run_params[key] = kwargs[key]
            else:
                raise TypeError('Parameter not defined: ' + key)
        return

    def write_input(self):
        '''This writes all of the input required to perform the structopt
        calculation. If a keyword is None, don't write it out'''

        structopt_write_params = {}
        for key in self.structopt_params:
            if self.structopt_params[key] != None:
                structopt_write_params[key] = self.structopt_params[key]        

        with open('structopt_inp.json', 'w') as f:
            json.dump(structopt_write_params, f, indent=1, sort_keys=True)


        if 'LAMMPS' in self.structopt_params['modules']:
            lammps_write_params = {}
            for key in self.lammps_params:
                if self.lammps_params[key] != None:
                    lammps_write_params[key] = self.lammps_params[key]

            with open('lammps_inp.json', 'w') as f:
                json.dump(lammps_write_params, f, indent=1, sort_keys=True)


        if 'STEM' in self.structopt_params['modules']:
            stem_write_params = {}
            for key in self.stem_params:
                if self.stem_params[key] != None:
                    stem_write_params[key] = self.stem_params[key]

            with open('stem_inp.json', 'w') as f:
                json.dump(stem_write_params, f, indent=1, sort_keys=True)

        return

    def read_input(self):
        '''Reads all of the input files'''

        with open('structopt_inp.json', 'r') as f:
            structopt_params = json.load(f)

        for key in structopt_params:
            self.structopt_params[key] = structopt_params[key]

        if 'LAMMPS' in self.structopt_params['modules']:
            with open('lammps_inp.json', 'r') as f:
                lammps_params = json.load(f)
                
            for key in lammps_params:
                self.lammps_params[key] = lammps_params[key]

        if 'STEM' in self.structopt_params['modules']:
            with open('stem_inp.json', 'r') as f:
                stem_params = json.load(f)
                
            for key in stem_params:
                self.stem_params[key] = stem_params[key]    
            
        return    

    def read_xyz(self, name='Bests'):
        '''This reads the contents of one xyz file outputted from structopt.
        To my knowledge, this is either the Bests-<filename>.xyz or the 
        indiv##.xyz file.'''

        filename = self.string_params['filename']
        f_dir = '{0}/{1}-rank0'.format(self.system_name, filename)
        
        if isinstance(name, str) and name.lower() == 'bests':
            f_name = '{0}/Bests-{1}.xyz'.format(f_dir, filename)
        else:
            f_name = '{0}/indiv{1:02}.xyz'.format(f_dir, name)

        all_atoms, all_fits = [], []

        with open(f_name) as f:
            i0 = -2
            n = 0
            for i, line in enumerate(f.readlines()):
                # First read the number of atoms
                if (i == i0 + n + 2):
                    n = int(line[:-1])
                    i0 = i
                    atoms = Atoms()
                # Now read the total energy
                elif i == i0 + 1:
                    all_fits.append(float(line[:-1]))
                elif i > i0 + 1 and i <= i0 + 1 + n:
                    atom, x, y, z = line[:-1].split()
                    x = float(x)
                    y = float(y)
                    z = float(z)
                    atoms.extend(Atom(atom, [x, y, z]))
                    all_atoms.append(atoms)
                else:
                    raise IOError("Error in xyz file: " + f_name)

        if isinstance(name, str) and name.lower() == 'bests':
            self.bests = {}
            self.bests['atoms'] = all_atoms
            self.bests['fits'] = all_fits
        else:
            self.indiv = {}
            self.indiv[name] = {}
            self.indiv[name]['atoms'] = all_atoms
            self.indiv[name]['fits'] = all_fits
            
        return

    def calculation_required(self):
        '''We only want a calculation to run when either the calculation is 
        not converged or an input parameter has changed'''

        if self.structopt_params != self.old_structopt_params:
            return True
        if self.lammps_params != self.old_lammps_params:
            return True
        if self.stem_params != self.old_stem_params:
            return True
        else:
            return False

    def get_best_atoms(self):
        '''This returns the best atoms object from the Bests- file'''
        self.calculate()
        if not hasattr(self, 'bests'):
            self.read_xyz('bests')
        return self.bests['atoms'][0]

    def get_best_fit(self):
        '''This returns the best energy from the Bests- file'''
        self.calculate()
        if not hasattr(self, 'bests'):
            self.read_xyz('bests')
        return self.bests['fits'][0]

    def get_generations(self):
        '''This returns a list of generations'''
        self.calculate()
        return self.gens

    def get_fits_mins(self):
        '''This returns a list of lowest fitness in each generation'''
        self.calculate()
        return self.fmins

    def get_fits_avgs(self):
        '''This returns a list of fit averages'''
        self.calculate()
        return self.favgs

    def get_fits_meds(self):
        '''This returns a list of fit medians'''
        self.calculate()
        return self.fmeds

    def get_fits_maxs(self):
        '''This returns a list of highest fitness in each generation'''
        self.calculate()
        return self.fmaxs

    def get_fit_stds(self):
        '''Returns the standard deviation of each generation'''
        self.calculate()
        return self.fstds

from structopt_run import *
