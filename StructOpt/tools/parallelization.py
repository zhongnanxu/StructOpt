import functools
import StructOpt

def serial(func):
    """A decorator that will only run the function if the core is rank 0.
    If the rank is non-zero, the function will return None."""

    if StructOpt.USE_MPI4PY:
        from mpi4py import MPI
        rank = MPI.COMM_WORLD.Get_rank()
    else:
        rank = 0

    if rank == 0:
        @functools.wraps(func)
        def wrapper(**kwargs):
            return func(**kwargs)
        return wrapper
    else:
        wrapper = functools.wraps(func, lambda *args, **kwargs: None)
        return wrapper

