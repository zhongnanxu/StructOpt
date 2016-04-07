from StructOpt.tools import get_best
import logging

def selection_switch(pop, nkeep, scheme, Optimizer):
    """Functions for selecting and pairing individuals
    for crossovers"""
    logger = logging.getLogger('default')
    if 'SEL' in Optimizer.debug:
        debug = True
    else:
        debug = False
    try:
        exec "from StructOpt.selection.{0} import {0}".format(scheme)
        newpop = eval('{0}(pop, nkeep, Optimizer)'.format(scheme))
    except NameError,e:
        logger.warning('Selection scheme not one of the available options! Check Document and spelling. Selection Scheme : {0}. {1}'.format(scheme,e), exc_info=True)
        logger.warning('No reordering or reduction applied')
        newpop = pop
    except Exception, e:
        logger.error('Issue in Selection scheme. Selection Scheme : {0}. {1}'.format(scheme,e), exc_info=True)
        logger.warning('No reordering or reduction applied')
        print 'ERROR: Issue in Selection scheme. Selection Scheme : '+repr(scheme)
        print e
        newpop = pop
    return newpop
