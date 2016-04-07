import StructOpt
import os
import time
import random
import logging
from StructOpt import structoptio
from StructOpt import tools
from StructOpt import generate
from StructOpt import switches
from StructOpt.switches.predator_switch import predator_switch
from StructOpt import fingerprinting
from StructOpt import post_processing as pp
from importlib import import_module
from ase import Atom, Atoms
from StructOpt.tools.setup_energy_calculator import setup_energy_calculator
from StructOpt.tools.check_structures import check_structures
from mpi4py import MPI

class Optimizer():
    __version__  = 'StructOpt_v2.0'


    def __init__(self):
        self.logger = logging.getLogger('default')
        for k, v in StructOpt.parameters.items():
            setattr(self, k, v)

        self.relaxation_modules = []
        for rm in self.relaxations:
            mod = import_module('StructOpt.fitness.{module_name}.{module_name}_eval'.format(module_name=rm))  # Import the module package
            cls = getattr(mod, '{cls_name}_eval'.format(cls_name=rm))  # Get's the class from the module package
            self.relaxation_modules.append(cls())

        self.fitness_modules = []
        for fm in self.modules:
            mod = import_module('StructOpt.fitness.{module_name}.{module_name}_eval'.format(module_name=fm))  # Import the module package
            cls = getattr(mod, '{cls_name}_eval'.format(cls_name=fm))  # Get's the class from the module package
            self.fitness_modules.append(cls())

        if self.restart_optimizer:
                self.logger.info('restarting output')
                outdict = structoptio.restart_output(self)
                self.__dict__.update(outdict)
                self.logger.info('Loading individual files')
                poplist = []
                for indfile in self.population:
                    ind = structoptio.read_individual(indfile)
                    poplist.append(ind)
                self.population = poplist
                self.logger.info('Loading bests')
                bestlist = []
                for bestfile in self.BESTS:
                    ind = structoptio.read_individual(bestfile)
                    bestlist.append(ind)
                self.BESTS = bestlist
                self.restart = True
                if self.structure == 'Defect':
                    bulk = structoptio.read_xyz(self.solidfile)
                    bulk.set_pbc(True)
                    bulk.set_cell(self.solidcell)
                    self.solidbulk = bulk.copy()
                else:
                    self.solidbulk = None
        else:
            self.convergence = False
            self.generation = 0
            self.Runtimes = [time.time()]
            self.Evaluations = list()
            self.CXs = list()
            self.Muts = list()
            self.cxattempts = 0
            self.mutattempts = list()
            self.BESTS = list()
            self.genrep = 0
            self.minfit = 0
            self.convergence = False
            self.overrideconvergence = False
            self.population = list()
            self.calc = None
            self.static_calc = None


    def algorithm_initialize(self):
        if self.restart_optimizer:
            self.logger.info('Successfully loaded optimizer from file')
        else:
            # Setup the output files
            self.logger.info('Initializing output for algorithm')
            outdict = structoptio.setup_output(self.filename, self.restart, self.nindiv,
                self.indiv_defect_write, self.genealogy, self.allenergyfile,
                self.fingerprinting, self.debug)
            self.__dict__.update(outdict)

            # Set starting convergence and generation
            self.logger.info('Initializing convergence, generation, and output monitoring stats')
            self.convergence = False
            self.overrideconvergence = False
            self.generation = 0

            # Prep output monitoring
            self.Runtimes = [time.time()]
            self.Evaluations = list()
            self.CXs = list()
            self.Muts = list()
            self.cxattempts = 0
            self.mutattempts = list()

            # Initialize random number generator
            random.seed(self.seed)

            # Initialize swap list variable
            if self.swaplist == None:
                # Use if concentrations in swaplist is unknown
                self.swaplist = [ [sym, c] for sym, c, m, u in self.atomlist ]
                swaplist = self.swaplist
            elif self.swaplist:
                swaplist = self.swaplist
            # Write the input parameters to the output file
            self.logger.info('Writing the input parameters to output file')
            structoptio.write_parameters(self)


    def algorithm_run(self):
        comm = MPI.COMM_WORLD
        rank = MPI.COMM_WORLD.Get_rank()
        if 'MA' in self.debug:
            debug = True
        else:
            debug = False
        if rank == 0:
            self.algorithm_initialize()
            self.logger.info('Beginning main algorithm loop')

        # Begin main algorithm loop
        self.convergence = False
        convergence = False
        while not convergence:
            if rank == 0:
                pop = self.population
                offspring = self.generation_set(pop)
                # Identify the individuals with an invalid fitness
                indiv = [ind for ind in offspring if ind.fitness == 0]
                # Evaluate the individuals with invalid fitness
                self.output.write('\n--Evaluate Structures--\n')
            else:
                indiv = []

            stro = ''
            if rank == 0:
                indiv, stro = check_structures(self, indiv)

            # Be careful here, the relaxations will update the indiv list
            # If there are multiple relaxations, they should be run in order,
            # so relaxation1 will run, update the structure, which will then
            # get fed into relaxation2, etc.
            # TODO Are these only run on rank0? If so, this code blockis fine.
            # If not, it needs to be updated!
            for m in range(len(self.relaxation_modules)):
                stro += 'Relaxing structure using {}\n'.format(self.relaxations[m])
                relax_out = self.relaxation_modules[m].evaluate_fitness(self, indiv, True)

                if rank == 0:
                    for i in range(len(indiv)):
                        indiv[i] = relax_out[i][0]
                        stro += relax_out[i][1]

            fits = []
            for m in range(len(self.fitness_modules)):
                stro += 'Evaluating fitness with module {}\n'.format(self.modules[m])
                out_part = self.fitness_modules[m].evaluate_fitness(self, indiv)
                fm = []
                for i in range(len(out_part)):
                    fm.append(out_part[i][0])
                    stro += out_part[i][1]
                fits.append(fm)

            if rank == 0:
                self.logger.info('Individual fitnesses of Generation # {0}'.format(self.generation))
                for i in range(len(indiv)):
                    fi = [fits[m][i] for m in range(len(self.fitness_modules))]
                    if None not in fi:
                        indiv[i].fitness = self.objective_function(fi, self.weights)
                        self.logger.info('Individual {0}: {1}'.format(indiv[i].history_index, indiv[i].fitness))
                self.output.write(stro)
                pop.extend(indiv)
                pop = self.generation_eval(pop)
                self.write()
            convergence = comm.bcast(self.convergence, root=0)

        if rank == 0:
            self.logger.info('Run algorithm stats')
            end_signal = self.algorithm_stats(self.population)
        else:
            end_signal = None
        end_signal = comm.bcast(end_signal, root=0)

        return end_signal


    def algorithm_stats(self, pop):
        self.output.write('\n----- Algorithm Stats -----\n')
        cxattempts = 0
        cxsuccess = 0
        for ats, sus in self.CXs:
            cxattempts += ats
            cxsuccess += sus
        mutslist = [[0, 0] for one in self.mutation_options]
        for one in self.Muts:
            for i in range(len(mutslist)):
                mutslist[i][0] += one[i][0]
                mutslist[i][1] += one[i][1]
        self.output.write('Total Number of Evaluations : {}\n'.format(repr(sum(self.Evaluations))))
        self.output.write('Average Number of Evaluations per Generation : {}\n'.format(repr(float(sum(self.Evaluations))/float(len(self.Evaluations)))))
        ttseconds = self.Runtimes[-1]-self.Runtimes[0]

        deltats = []
        for i in range(1, len(self.Runtimes)):
            deltats.append(self.Runtimes[i]-self.Runtimes[i-1])
        maxs = [(ind, value) for ind, value in enumerate(deltats) if value == max(deltats)]
        maxtgen = maxs[0][0]-1
        maxts = maxs[0][1]
        mins = [(ind, value) for ind, value in enumerate(deltats) if value == min(deltats)]
        mintgen = mins[0][0]-1
        mints = mins[0][1]
        avgts = sum(deltats)/len(deltats)
        self.output.write('Total Length of GA run : {}\n'.format(tools.convert_time(ttseconds)))
        self.output.write('Average time per generation : {}\n'.format(tools.convert_time(avgts)))
        self.output.write('Maximum time for generation {} : {}\n'.format(repr(maxtgen), tools.convert_time(maxts)))
        self.output.write('Minimum time for generation {} : {}\n'.format(repr(mintgen), tools.convert_time(mints)))
        self.output.write('Attempted Crossovers: {}\n'.format(repr(cxattempts)))
        self.output.write('Successful Crossovers: {}\n'.format(repr(cxsuccess)))
        self.output.write('Mutations:\n')

        i = 0
        self.output.write('{}\n'.format(mutslist))
        for opt in self.mutation_options:
            self.output.write('    Attempted {} : {}\n'.format(opt, repr(mutslist[i][0])))
            self.output.write('    Successful {} : {}\n'.format(opt, repr(mutslist[i][1])))
            i += 1
        if self.best_inds_list:
            BESTS = tools.BestInds(pop, self.BESTS, self, writefile = True)
        self.close_output()
        end_signal = 'Genetic Algorithm Finished'

        return end_signal


    def objective_function(self, fits, weights):
        # return sum([weight*fit.fitness for fit, weight in zip(self.modules, self.weights)])
        return sum([ fit*weight for fit, weight in zip(fits, weights)])


    def check_pop(self, pop):
        # Gather all the energies/fitnesses
        if self.output_format == 'totalenergy':
            complist = [ind.energy for ind in pop]
        elif self.output_format == 'formation_energy':
            complist = []
            for ind in pop:
                solid = Atoms()
                solid.extend(ind[0])
                solid.extend(ind.bulki)
                energy = ind.energy
                for sym, c, m, u in self.atomlist:
                    nc = len([atm for atm in solid if atm.symbol == sym])
                    energy -= float(nc)*float(u)
                complist.append(energy)
        elif self.output_format == 'formation_energy_per_int':
            complist = []
            for ind in pop:
                solid = Atoms()
                solid.extend(ind[0])
                solid.extend(ind.bulki)
                energy = ind.energy
                for sym, c, m, u in self.atomlist:
                    nc = len([atm for atm in solid if atm.symbol == sym])
                    energy -= float(nc)*float(u)
                energy = energy/self.natoms
                complist.append(energy)
        elif self.output_format == 'formation_energy2':
            complist = [(ind.energy - ind.purebulkenpa*(ind[0].get_number_of_atoms()+ind.bulki.get_number_of_atoms()))/(ind[0].get_number_of_atoms()+ind.bulki.get_number_of_atoms()-ind.natomsbulk) for ind in pop]
        elif self.output_format == 'energy_per_atom':
            complist = [ind.energy/(ind[0].get_number_of_atoms()+ind.bulki.get_number_of_atoms()) for ind in pop]
        else:
            complist = [ind.fitness for ind in pop]

        # Calcluate and print the Stats
        length = len(pop)
        mean = sum(complist) / length
        complist.sort()
        medium = complist[length/2]
        sum2 = sum(x*x for x in complist)
        std = abs(sum2 / length - mean**2)**0.5
        mine = min(complist)
        maxe = max(complist)

        self.output.write('\n----Stats----\n')
        self.output.write('  Min '+repr(mine)+'\n')
        self.output.write('  Max '+repr(maxe)+'\n')
        self.output.write('  Avg '+repr(mean)+'\n')
        self.output.write('  Medium '+repr(medium)+'\n')
        self.output.write('  Std '+repr(std)+'\n')
        self.output.write('  Genrep '+repr(self.genrep)+'\n')
        self.summary.write("{0: <10} {1:<10.4f} {2:<10.4f} {3:<10.4f} {4:<10.4f} {5:<10.4f} {6: <25}\n".format(
                self.generation, mine, mean, medium, maxe, std, time.asctime(time.localtime(time.time()))))

        outputlist = []
        for ind in pop:
            outputlist.append([ind.fitness, ind.energy/ind[0].get_number_of_atoms()])
        fitness_min = min([fitness for fitness, eatom in outputlist])
        eatom_min = [one[1] for one in outputlist if one[0] == fitness_min][0]
        # print 'Gen, fitness, eatom, chi2', self.generation, fitness_min, eatom_min, fitness_min-eatom_min

        # Set new index values and write population
        index1 = 0
        for ind in pop:
            ind.index = index1
            index1 += 1
        structoptio.write_pop(self, pop)

        if self.allenergyfile:
            for ind in pop:
                self.tenergyfile.write(repr(ind.energy)+' ')
            self.tenergyfile.write('\n')

        # Check Convergence of population based on fitness
        fitnesses = [ind.fitness for ind in pop]
        popmin = min(fitnesses)
        popmean = sum(fitnesses) / len(fitnesses)
        sum2 = sum(x*x for x in fitnesses)
        popstd = abs(sum2 / len(fitnesses) - popmean**2)**0.5
        convergence = False
        if self.convergence_scheme == 'gen_rep_min':
            if self.generation < self.maxgen:
                if self.generation == 0:
                    self.minfit = popmin
                if abs(self.minfit - popmin) < self.tolerance:
                    self.genrep += 1
                else:
                    self.genrep = 0
                    self.minfit = popmin
                if self.genrep > self.reqrep:
                    self.convergence = True
            else:
                self.convergence = True
        elif self.convergence_scheme == 'gen_rep_avg':
            if self.generation < self.maxgen:
                if self.generation == 0:
                    self.minfit = popmean
                if abs(self.minfit - popmean) < self.tolerance:
                    self.genrep += 1
                else:
                    self.genrep = 0
                    self.minfit = popmean
                if self.genrep > self.reqrep:
                    self.convergence = True
            else:
                self.convergence = True
        elif self.convergence_scheme == 'std':
            if popstd < self.tolerance:
                self.convergence = True
        else:# self.convergence_scheme == 'max_gen':
            if self.generation > self.maxgen:
                self.convergence = True
        if self.convergence:
            self.logger.info("Successfully converged!\n")

        # Flush output to files
        self.output.flush()
        self.summary.flush()
        for ind in self.files:
            ind.flush()
        if self.indiv_defect_write:
            for ind in self.ifiles:
                ind.flush()
        if self.genealogy: self.Genealogyfile.flush()
        if self.allenergyfile: self.tenergyfile.flush()
        if 'MA' in self.debug: self.debugfile.flush()
        if self.fingerprinting:
            self.fpfile.flush()
            self.fpminfile.flush()
        return self


    def close_output(self):
        localtime = time.asctime( time.localtime(time.time()) )
        for ind in self.files:
            ind.close()
        self.output.write('Local time : {}\n'.format(repr(localtime)))
        self.output.write('End of Execution\n')
        self.summary.close()
        self.output.close()
        if self.genealogy: self.Genealogyfile.close()
        if self.allenergyfile: self.tenergyfile.close()
        if 'MA' in self.debug: self.debugfile.close()
        if self.fingerprinting:
            self.fpfile.close()
            self.fpminfile.close()


    def generation_eval(self, pop):
        emx = max(ind.energy for ind in pop)
        emn = min(ind.energy for ind in pop)
        for ind in pop:
            ind.tenergymx = emx
            ind.tenergymin = emn

        # DEBUG: Write relaxed individual
        if 'MA' in self.debug:
            if self.generation > 0:
                structoptio.write_xyz(self.debugfile, pop[self.nindiv][0], 'First Relaxed Offspring {}'.format(repr(pop[self.nindiv-1].energy)))

                # DEBUG: Write relaxed ind in solid
                if self.structure == 'Defect' or self.structure == 'Surface':
                    structoptio.write_xyz(self.debugfile, pop[self.nindiv].bulki, 'First Relaxed bulki {}'.format(repr(pop[self.nindiv-1].energy)))
                    sols = pop[self.nindiv][0].copy()
                    sols.extend(pop[self.nindiv].bulki)
                    structoptio.write_xyz(self.debugfile, sols, 'First from Invalid-ind + Bulki '.format(repr(pop[self.nindiv].energy)))
                    sols = pop[self.nindiv][0].copy()
                    sols.extend(pop[self.nindiv].bulko)
                    structoptio.write_xyz(self.debugfile, sols, 'First from Invalid-ind + Bulko {}'.format(repr(pop[self.nindiv].energy)))
        if self.generation == 0:
            self.logger.info('Initializing Bests list')
            self.BESTS = list()
        if self.best_inds_list:
            self.BESTS = tools.BestInds(pop, self.BESTS, self, writefile = True)

        # Determine survival based on fitness predator
        if 'lambda, mu' not in self.algorithm_type:
            pop = tools.get_best(pop, len(pop))
        if self.fingerprinting:
            self.logger.info('Writing fingerprint files')
            for one in pop:
                self.fpfile.write(repr(fingerprinting.fingerprint_dist(pop[0].fingerprint, one.fingerprint))+' '+repr(one.energy)+' ')  # TODO Fix this
            self.fpfile.write('\n')
            self.fpminfile.write(repr(pop[0].fingerprint)+'\n')
            self.fpminfile.write(repr(pop[0].energy)+'\n')
        nevals = len(pop)/2
        if self.generation != 0:
            self.logger.info('Applying predator')
            pop = predator_switch(pop, self)
        else:
            self.genrep = 0
            self.minfit = 0

        # Evaluate population
        self.logger.info('Checking population for convergence')
        self.check_pop(pop)

        # Update general output tracking
        if self.generation != 0:
            histlist = []
            for ind in pop:
                histlist.append(ind.history_index)
            self.Runtimes.append(time.time())
            self.Evaluations.append(nevals)
            cxsuccess = 0
            mutsuccess = []
            for one in histlist:
                if '+' in one:
                    cxsuccess += 1
                if 'm' in one:
                    mutsuccess.append(one)
            self.CXs.append((self.cxattempts, cxsuccess))
            mutslist = [[0, 0] for one in self.mutation_options]
            for one in mutsuccess:
                for two, opt in self.mutattempts:
                    if one == two:
                        index = [ind for ind, value in enumerate(
                            self.mutation_options) if value == opt][0]
                        mutslist[index][1] += 1
            for one, opt in self.mutattempts:
                index = [ind for ind, value in enumerate(
                self.mutation_options) if value == opt][0]
                mutslist[index][0] += 1
            self.Muts.append(mutslist)
            self.output.write('\n----- Generation Stats -----\n')
            self.output.write('Attempted Crossovers: {}\n'.format(repr(self.cxattempts)))
            self.output.write('Successful Crossovers: {}\n'.format(repr(cxsuccess)))
            self.output.write('Mutations:\n')
            for i, opt in enumerate(self.mutation_options):
                self.output.write('    Attempted {} : {}\n'.format(opt, repr(mutslist[i][0])))
                self.output.write('    Successful {} : {}\n'.format(opt, repr(mutslist[i][1])))
        self.generation += 1

        # Set new index values
        for index1, ind in enumerate(pop):
            ind.index = index1

        self.population = pop
        return pop


    def generation_set(self, pop):
        # # Setting up energy calculators from relaxation methods
        # self.calc = setup_energy_calculator(self.relaxations, True)
        # Set up calculator for fixed region calculations
        # if self.fixed_region:
        #    self.static_calc = self.calc # May need to copy this
        #    self.calc = tools.setup_fixed_region_calculator(self)
        self.output.write('\n-------- Generation {} --------\n'.format(repr(self.generation)))
        self.files[self.nindiv].write('Generation {}\n'.format(str(self.generation)))

        if self.generation == 0:
            self.logger.info('Initializing structures')
            offspring = self.initialize_structures()
            self.population = offspring
        else:
            for i in range(len(pop)):
                # Reset History index
                pop[i].history_index = repr(pop[i].index)

            # Select the next generation individuals
            offspring = switches.selection_switch(pop, self.nindiv,
                        self.selection_scheme, self)

            # Clone the selected individuals
            offspring = [off1.duplicate() for off1 in offspring]

            # Apply crossover to the offspring
            self.output.write('\n--Applying Crossover--\n')
            cxattempts = 0
            for child1, child2 in zip(offspring[::2], offspring[1::2]):
                if random.random() < self.cxpb:
                    child1, child2 = switches.crossover_switch(child1, child2, self)
                    cxattempts += 2
            self.cxattempts = cxattempts

            # DEBUG: Write first child
            if 'MA' in self.debug:
                structoptio.write_xyz(self.debugfile, offspring[0][0], 'First Child '+
                    repr(offspring[0].history_index))

            # Apply mutation to the offspring
            self.output.write('\n--Applying Mutation--\n')
            mutattempts = []
            muts = []
            for mutant in offspring:
                if random.random() < self.mutpb:
                    if self.mutant_add:
                        mutant = mutant.duplicate()
                    mutant, optsel = switches.moves_switch(mutant, self)
                    mutattempts.append([mutant.history_index, optsel])
                    if self.mutant_add:
                        muts.append(mutant)
            if self.mutant_add:
                offspring.extend(muts)
            self.mutattempts = mutattempts
            # DEBUG: Write first offspring
            if 'MA' in self.debug:
                structoptio.write_xyz(self.debugfile, muts[0][0], 'First Mutant {}\n'.format(repr(muts[0].history_index)))

        return offspring


    def initialize_structures(self):
        self.output.write('\n----Initialize Structures----\n')
        # self.logger.info('Initializing Structures')
        # Initialize Population - Generate a list of ncluster individuals
        # Set bulk and index atributes
        if self.restart:
            self.logger.info('Loading previous population')
            pop = generate.get_restart_population(self)
        else:
            self.logger.info('Generating new population')
            pop = generate.get_population(self)
        if 'MA' in self.debug:
            structoptio.write_xyz(self.debugfile, pop[0][0], 'First Generated Individual')

        # Use if concentration of interstitials is unknown
        if self.swaplist:
            mutlist = self.mutation_options
            self.mutation_options = ['IntSwapLocal']
            for i in range(len(pop)):
                one = pop[i]
                one.swaplist = copy.deepcopy(swaplist)
                if random.random() < 0.25:
                    pop[i], opt = switches.moves_switch(one, self)
            self.mutation_options = mutlist

        # Write Initial structures to files
        self.output.write('\n---Starting Structures---\n')
        structoptio.write_pop(self, pop)

        # Print number of atoms to Summary file
        if self.structure == 'Defect' or self.structure == 'Surface':
            natstart = len(pop[0][0])+len(pop[0].bulki)
        else:
            natstart = len(pop[0][0])
        if not self.restart:
            if self.structure == 'Defect':
                self.summary.write('Defect Run Pure Bulk Energy per Atom : {}\n'.format(repr(self.purebulkenpa)))
            else:
                self.summary.write(self.structure+' Run : {}\n'.format(repr(0)))
            self.summary.write('Natoms '+repr(natstart)+ '\n')
            # Print data headers to summary file
            self.summary.write("{0: <10} {1: <10} {2: <10} {3: <10} {4: <10} {5: <10} {6: <25}\n".format(
                    'Gen', 'Fitmin', 'Fitavg', 'Fitmedium', 'Fitmax', 'STD', 'Time'))
        offspring = pop
        return offspring


    def run(self):
        cwd = os.getcwd()

        self.algorithm_run()

        if self.postprocessing:
            self.logger.info('Running Post-processing')
            path = os.path.join(os.getcwd(), '{0}-rank0'.format(self.filename))
            os.chdir(path)
            if self.genealogytree:
                pp.read_output(os.getcwd(), genealogytree=True, natoms=self.natoms)
            else:
                pp.read_output(os.getcwd(), genealogytree=False, natoms=self.natoms)
            os.chdir(cwd)
        if self.lattice_concentration:
            if self.structure == 'Defect':
                self.logger.info('Running lattice concentration check')
                path = os.path.join(os.getcwd(), '{0}-rank0'.format(self.filename))
                os.chdir(path)
                if self.best_inds_list:
                    pp.get_lattice_concentration(os.path.join(os.getcwd(), 'Bulkfile.xyz'), os.path.join(os.getcwd(), 'Bests-{}.xyz'.format(self.filename)))
                else:
                    pp.get_lattice_concentration(os.path.join(os.getcwd(), 'Bulkfile.xyz'), os.path.join(os.getcwd(), 'indiv00.xyz'))
                os.chdir(cwd)


    def read(self, optfile):
        parameters = structoptio.read_parameter_input(optfile, True)
        self.__dict__.update(parameters)
        outdict = structoptio.restart_output(self)
        self.__dict__.update(outdict)
        poplist = []

        for indfile in self.population:
            ind = structoptio.read_individual(indfile)
            poplist.append(ind)
        self.population = poplist
        bestlist = []

        for bestfile in self.BESTS:
            ind = structoptio.read_individual(bestfile)
            bestlist.append(ind)
        self.BESTS = bestlist
        self.restart = True
        return self


    def write(self, filename = None, restart = True):
        if filename:
            structoptio.write_optimizer(self, filename, restart)
        else:
            structoptio.write_optimizer(self, self.optimizerfile, restart)
        return



if __name__ == "__main__":
    import sys
    input = sys.argv[1]

    import StructOpt
    StructOpt.setup(input)

    optimizer = Optimizer()
    optimizer.run()
