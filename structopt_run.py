# Copyright (C) 2016 - Zhongnan Xu
'''Contains the functions required for running structopt jobs'''

from structopt import *
import StructOpt

def calculate(self):
    '''Generate necessary files in working directory and run
    mast'''

    if self.status == 'running':
        raise StructoptRunning('Running', os.getcwd())
    # if (self.status == 'done'
    #     and self.converged == False):
    #     raise StructoptNotConverged('Not Converged', os.getcwd())
    if self.calculation_required() or self.status == 'empty':
        self.write_input()
        self.run()
        self.status = 'running'
    return

Structopt.calculate = calculate

def run(self):
    '''This function writes the submit script and submits it'''

    self.write_submit()

    sub_cmd = 'qsub'
    p = Popen(['qsub', 'submit.sh'], stdout=PIPE, stderr=PIPE)
    out, err = p.communicate()

    with open('jobid', 'w') as f:
        f.write(out)

    raise StructoptSubmitted(out)

    return

Structopt.run = run

def write_submit(self):
    '''This function writes the submit script. It will be depend on the
    environment we are in'''

    # Load up some variables
    
    name = self.calcdir
    inp_file = 'structopt_inp.json'
    nodes = self.run_params['nodes']
    ppn = self.run_params['ppn']
    queue = self.run_params['queue']
    walltime = '{0}:00:00'.format(self.run_params['walltime'])
    mpi_cmd = self.run_params['mpirun']
    py_cmd = self.run_params['python']

    # Start writing the script
    script = '#!/bin/bash\n'
    script += '#PBS -N {0}\n'.format(name)
    script += '#PBS -q {0}\n'.format(queue)
    script += '#PBS -l nodes={0}:ppn={1}\n'.format(nodes, ppn)
    script += '#PBS -l walltime={0}\n'.format(walltime)
    script += '#PBS -j oe\n\n'

    # If we are running lammps, we need to set the LAMMPS_COMMAND
    if 'LAMMPS' in self.structopt_params['modules']:
        if self.lammps_params['pair_style'] == 'meam':
            lmp_cmd = '$HOME/bin/lmp_serial_meam'
        else:
            lmp_cmd = '$HOME/bin/lmp_serial_eam'
        script += 'export LAMMPS_COMMAND={0}\n\n'.format(lmp_cmd)

    script += 'cd $PBS_O_WORKDIR\n'
        
    # Load up the Optimizer.py path
    opt_cmd = os.path.dirname(StructOpt.__file__) + '/Optimizer.py'

    # Run structopt
    run_cmd = '{mpi_cmd} {py_cmd} {opt_cmd} {inp_file} | tee structopt.out\n\n'
    script += run_cmd.format(**locals())
    
    with open('submit.sh', 'w') as f:
        f.write(script)

    return
    
Structopt.write_submit = write_submit    
