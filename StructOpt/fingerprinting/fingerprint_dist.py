import numpy
from scipy.spatial.distance import cosine

def fingerprint_dist(fingerprint1, fingerprint2):
    """Function to calculate the cosine distance between two fingerprint functions"""

    return cosine(fingerprint1, fingerprint1)/2.0
