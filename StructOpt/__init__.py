"""Functions for use in optimizer"""


try:
    import ase
except ImportError:
    raise ImportError("ASE must be installed to use Structopt.")


# See https://github.com/mpi4py/mpi4py/blob/4b22c6c8ed73cd8eabdaa60a3cec0b804c1036cb/demo/init-fini/test_1.py
#from mpi4py import rc
#rc.initialize = False


def setup(input):
    import time
    from structoptio.read_parameter_input import read_parameter_input, set_default_parameters
    import structoptio.logger_utils
    parameters = read_parameter_input(input)
    if parameters["USE_MPI4PY"]:
        try:
            from mpi4py import MPI
        except ImportError:
            raise ImportError("mpi4py must be installed to use StructOpt.")
        parameters["rank"] = MPI.COMM_WORLD.Get_rank()
    else:
        parameters["rank"] = 0

    if "loggername" not in parameters:
        parameters["loggername"] = "{0}-rank{1}-{2}.log".format(parameters["filename"], parameters["rank"], time.strftime("%Y_%m%d_%H%M%S"))
    else:
        raise ValueError("'loggername' should not be defined in the input file currently. If you think you want to define it, talk to the developers about why.")

    if parameters["rank"] == 0:
        logger = structoptio.logger_utils.initialize_logger(filename=parameters["loggername"], name="default")
    else:
        logger = structoptio.logger_utils.initialize_logger(filename=parameters["loggername"], name="default", disable_output=True)

    logger_by_rank = structoptio.logger_utils.initialize_logger(filename=parameters["loggername"], name="by-rank")

    parameters = set_default_parameters(parameters)

    globals()["parameters"] = parameters
    return None


from Optimizer import Optimizer

# Used for `from StructOpt import *`
__all__ = ["Optimizer", "setup", "parameters"]
