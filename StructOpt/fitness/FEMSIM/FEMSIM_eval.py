import subprocess
import shlex
import sys
import json
import time
import numpy as np
import os
from StructOpt.fileio.write_xyz import write_xyz
import logging
import math
import shutil
from mpi4py import MPI

class FEMSIM_eval(object):
    def __init__(self):
        self.args = self.read_inputs()

        #self.step_number = 0

        self.vk = np.multiply(self.args['thickness_scaling_factor'], self.vk)  # Multiply the experimental data by the thickness scaling factor


    def read_inputs(self):
        args = json.load(open('femsim_inp.json'))

        data = open(args['vk_data_filename']).readlines()
        data.pop(0)  # Comment line
        data = [line.strip().split()[:2] for line in data]
        data = [[float(line[0]), float(line[1])] for line in data]
        k, vk = zip(*data)
        # Set k and vk data for chi2 comparison
        self.k = np.array(k)
        self.vk = np.array(vk)
        return args


    def update_parameters(self, **kwargs):
        #self.step_number += 1

        #self.args['aberation_coef'] += 1

        for key, value in kwargs.items():
            self.args[key] = value

    def evaluate_fitness(self, Optimizer, individ):
        logger = logging.getLogger('by-rank')
        rank = MPI.COMM_WORLD.Get_rank()
        out = []
        if rank==0:
            femsimfiles = '{filename}-rank0/FEMSIMFiles'.format(filename=Optimizer.filename)
            if not os.path.exists(femsimfiles):
                os.mkdir(femsimfiles)

            commands = []
            indiv_folders = []
            bases = []
            for i in range(len(individ)):
                indiv_folder, paramfilename, base = self.setup_individual_evaluation(Optimizer, individ[i], i)
                command = '-wdir {dir} {femsim_command} {base} {paramfilename}'.format(dir=indiv_folder, femsim_command=os.getenv('FEMSIM_COMMAND'), base=base, paramfilename=paramfilename)
                commands.append(command)
                indiv_folders.append(indiv_folder)
                bases.append(base)
            self.run(commands)

            chisqs = []
            for i, folder in enumerate(indiv_folders):
                vk = self.get_vk_data(folder, bases[i])
                chisq = self.chi2(vk)
                chisqs.append(chisq)
                logger.info('Individual {0} for FEMSIM evaluation had chisq {1}'.format(i, chisq))
            out = [(chisq, '') for chisq in chisqs]
            print(chisqs)

        out = MPI.COMM_WORLD.bcast(out, root=0)
        return out

    def setup_individual_evaluation(self, Optimizer, individ, i):

        logger = logging.getLogger('by-rank')

        logger.info('Received individual HI = {0} for FEMSIM evaluation'.format(individ.history_index))

        # Make individual folder and copy files there
        indiv_folder = '{filename}-rank0/FEMSIMFiles/Individual{i}'.format(filename=Optimizer.filename, i=i)
        if not os.path.exists(indiv_folder):
            os.mkdir(indiv_folder)
        if not os.path.isfile(os.path.join(indiv_folder, self.args['vk_data_filename'])):
            shutil.copy(self.args['vk_data_filename'], os.path.join(indiv_folder, self.args['vk_data_filename']))

        paramfilename = self.args['parameter_filename']
        shutil.copy(paramfilename, indiv_folder)  # Not necessary?
        self.write_paramfile(os.path.join(indiv_folder, paramfilename), Optimizer, individ, i)

        base = 'indiv{i}'.format(i=individ.history_index) # TODO Add generation number
        return indiv_folder, paramfilename, base

    def write_paramfile(self, paramfilename, Optimizer, individ, i):
        # Write structure file to disk so that the fortran femsim can read it in
        #ase.io.write('structure_{i}.xyz'.format(i=individ.history_index), individ[0])
        data = "{} {} {}".format(self.args['xsize'], self.args['ysize'], self.args['zsize'])
        write_xyz('structure_{i}.xyz'.format(i=individ.history_index), individ[0], data)

        with open(paramfilename, 'w') as f:
            f.write('# Parameter file for generation {gen}, individual {i}\n'.format(gen=Optimizer.generation, i=individ.history_index))
            f.write('{}\n'.format(os.path.join(os.getcwd(), 'structure_{i}.xyz'.format(i=individ.history_index))))
            f.write('{}\n'.format(self.args['vk_data_filename']))
            f.write('{}\n'.format(self.args['Q']))
            f.write('{} {} {}\n'.format(self.args['nphi'], self.args['npsi'], self.args['ntheta']))
            f.write('{}\n'.format(self.args['thickness_scaling_factor']))


    def run(self, commands):
        commands = ['-np 1 {command}'.format(command=command) for command in commands]  # TODO correctly allocate cores
        command = 'mpiexec {}'.format(' : '.join(commands))
        print("RUNNING FEMSIM!:")
        print(command)
        self.run_subproc(command)


    def run_subproc(self, args):
        """ args should be the string that you would normally run from bash """
        #print("Running (via python): {0}".format(args))
        sargs = shlex.split(args)
        p = subprocess.Popen(sargs, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output = []
        for nextline in iter(p.stdout.readline, ""):
            sys.stdout.write(nextline)
            output.append(nextline)
            sys.stdout.flush()
        poutput = p.stdout.read()
        perr = p.stderr.read()
        preturncode = p.wait()
        if(preturncode != 0):
            print("{0} exit status: {1}".format(args, preturncode))
            print("{0} failed: {1}".format(args, perr))
        return ''.join(output)

    def get_vk_data(self, folder, base):
        data = open(os.path.join(folder, 'vk_initial_{base}.txt'.format(base=base))).readlines()
        data = [line.strip().split()[:2] for line in data]
        data = [[float(line[0]), float(line[1])] for line in data]
        vk = np.array([vk for k, vk in data])
        return vk


    def chi2(self, vk):
        return np.sum(((self.vk - vk) / self.vk)**2) / len(self.k)

