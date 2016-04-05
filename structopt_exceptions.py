# Copyright (C) 2016 - Zhongnan Xu
'''This module contains the exceptions'''

from exceptions import Exception

class StructoptUnknownState(Exception):
    pass

class StructoptRunning(Exception):
    pass

class StructoptSubmitted(Exception):
    def __init__(self, jobdir):
        self.jobdir = jobdir
    def __str__(self):
        return repr(self.jobdir)
