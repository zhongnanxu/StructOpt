This example runs a Au18 nanoparticle through 5 generations. It uses LAMMPS to both relax the atoms object and calculate its fitness (total energy)

- Make sure ASE is installed and correctly reference in your PYTHONPATH

- Ensure the environment variable LAMMPS_COMMAND is set to a lmp_serial executable that can run an EAM potential.

- copy the Optimizer.py script to another location. Due to some weird path stuff, searching the local directory of StructOpt/StructOpt/Optimizer.py breaks its functionality. It works correctly when the Optimizer.py is NOT in the StructOpt/StructOpt directory and StructOpt is added to your PYTHONPATH

- When inside this directory, type

python /path/to/Optimizer.py structopt_inp.json

- To rerun the job, delete all of the output files, which all start with "Output-rank"
