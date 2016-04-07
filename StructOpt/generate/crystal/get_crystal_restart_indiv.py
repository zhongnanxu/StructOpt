from StructOpt.structoptio import read_xyz
from StructOpt.generate.Individual import Individual
from StructOpt.tools import find_top_layer

def get_crystal_restart_indiv(Optimizer, indiv):
    """
    Function to generate an structopt Individual class object containing
        a surface structure from a previously existing structure
    Inputs:
        Optimizer = structopt Optimizer class
        indiv = ASE Atoms object containing the previously existing structure
    Outputs:
        individ = structopt Individual class object containing surface structure data
    *** WARNING: This function is currently degenerate!  ***
    """
    crys = read_xyz(Optimizer.crysfile)
    #Recover cell from Structure Summary file
    # f = open(Optimizer.files[-1],'r')
#     sline = f.readline()
#     lines = f.readlines()
#     popbygen = []
#     n=0
#     for line in lines:
#         if 'Generation' in line:
#             if len(popbygen) != 0:
#                 popbygen.append(genlist)
#             genlist = []
#         else:
#             genlist.append(line)
#     f.close()
    cells = Optimizer.cryscell
    crys.set_cell(cells)
    individ=Individual(crys)
    return individ
