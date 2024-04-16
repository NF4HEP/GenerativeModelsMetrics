import os
import sklearn # type: ignore
import numpy as np
import pandas as pd # type: ignore
from matplotlib import pyplot as plt # type: ignore
import tensorflow as tf
import tensorflow_probability as tfp
import numpy as np
import random
from typing import List, Tuple, Dict, Callable, Union, Optional

def MultiNormalFromMixtureGaussian(ncomp: int,
                                   ndims: int,
                                   eps_loc: float = 0.,
                                   eps_scale: float = 0.,
                                   seed: int = 0,
                                   scale_def: Optional[str] = None, # could be None, std, cov, off
                                   nsamples: int = 50_000
                                  ) -> tfp.distributions.MultivariateNormalTriL: 
    reset_random_seeds(seed)
    loc: np.ndarray = np.random.sample(ndims) * 10
    loc_eps_np: np.ndarray = np.random.uniform(loc - eps_loc, loc + eps_loc)
    loc_eps: tf.Tensor = tf.constant(loc_eps_np, dtype = tf.float64)
    mix = MixtureGaussian(ncomp = ncomp,
                          ndims = ndims,
                          eps_loc = eps_loc,
                          eps_scale = eps_scale,
                          seed = seed)
    samp = mix.sample(nsamples).numpy()
    df = pd.DataFrame(samp)
    correlation_matrix_np: np.ndarray = df.corr().to_numpy()
    if scale_def is not None:
        for i in range(ndims):
            for j in range(ndims):
                if i == j:
                    correlation_matrix_np[i,j] = correlation_matrix_np[i,j] * (1 + eps_scale)
                    #if scale_def == "std":
                    #    correlation_matrix_np[i,j] = correlation_matrix_np[i,j] * (1 + eps_scale)
                    #elif scale_def == "cov":
                    #    correlation_matrix_np[i,j] = correlation_matrix_np[i,j] * (1 + eps_scale)
                    #elif scale_def == "off":
                    #    correlation_matrix_np[i,j] = correlation_matrix_np[i,j] * (1 + eps_scale)
                    #else:
                    #    raise Exception("scale_def should be 'None', 'std', 'cov', or 'off'.")
                else:
                    if scale_def == "std":
                        correlation_matrix_np[i,j] = correlation_matrix_np[i,j]
                    elif scale_def == "cov":
                        correlation_matrix_np[i,j] = correlation_matrix_np[i,j] * (1 + eps_scale)
                    elif scale_def == "off":
                        correlation_matrix_np[i,j] = correlation_matrix_np[i,j] * np.max([0.,(1 - eps_scale)])
                    else:
                        raise Exception("scale_def should be 'None', 'std', 'cov', or 'off'.")
    #print(f"correlation matrix: {correlation_matrix_np}")
    if not np.all(np.linalg.eigvals(correlation_matrix_np) >= 0):
        raise ValueError("The correlation matrix is not semi positive-definite.")
    covariance_matrix: tf.Tensor = tf.constant(correlation_matrix_np, dtype = tf.float64)
    scale_eps: tf.Tensor = tf.linalg.cholesky(covariance_matrix) # type: ignore
    mvn = tfp.distributions.MultivariateNormalTriL(loc = loc_eps, 
                                                   scale_tril = scale_eps)
    return mvn

def MixtureGaussian(ncomp: int,
                    ndims: int,
                    eps_loc: float = 0.,
                    eps_scale: float = 0.,
                    seed: int = 0) -> tfp.distributions.Mixture:
    """
    Correlated mixture of Gaussians used in https://arxiv.org/abs/2302.12024 
    with ncomp = 3 and ndims varying from 4 to 1_000
    
    Args:
        ncomp: int, number of components
        ndims: int, number of dimensions
        seed: int, random seed

    Returns:
        targ_dist: tfp.distributions.Mixture, mixture of Gaussians
    """
    targ_dist: tfp.distributions.Mixture = MixMultiNormal1(ncomp, ndims, eps_loc, eps_scale, seed = seed)
    return targ_dist

def MixNormal1(n_components: int = 3,
               n_dimensions: int = 4,
               eps_loc: float = 0.,
               eps_scale: float = 0.,
               seed: int = 0) -> tfp.distributions.Mixture:
    """
    Defines a mixture of 'n_components' Normal distributions in 'n_dimensions' dimensions 
    with means and stddevs given by the tensors 'loc' and 'scale' with shapes 
    '(n_components,n_dimensions)'.
    The components are mixed according to the categorical distribution with probabilities
    'probs' (with shape equal to that of 'loc' and 'scale'). This means that each component in each
    dimension can be assigned a different probability.

    The resulting multivariate distribution has small correlation.

    Note: The functions 'MixNormal1' and 'MixNormal1_indep'
    generate identical samples, different from the samples generated by
    'MixNormal2' and 'MixNormal2_indep' (also identical).
    
    Args:
        n_components: int, number of components
        n_dimensions: int, number of dimensions
        seed: int, random seed
        
    Returns:
        mix_gauss: tfp.distributions.Mixture, mixture of Gaussians
    """
    reset_random_seeds(seed)
    loc: np.ndarray = np.random.sample([n_components, n_dimensions])*10
    loc_eps: np.ndarray = np.random.uniform(loc-eps_loc, loc+eps_loc)
    scale: np.ndarray = np.random.sample([n_components,n_dimensions])
    scale_eps: np.ndarray = np.random.uniform(scale-eps_scale, scale+eps_scale)
    probs: np.ndarray = np.random.sample([n_dimensions,n_components])
    components: List[tfp.distributions.Normal] = []
    for i in range(n_components):
        components.append(tfp.distributions.Normal(loc = loc_eps[i],
                                                   scale = scale_eps[i]))
    mix_gauss: tfp.distributions.Mixture = tfp.distributions.Mixture(
        cat = tfp.distributions.Categorical(probs=probs),
        components = components,
        validate_args = True)
    return mix_gauss
    
def MixNormal2(n_components: int = 3,
               n_dimensions: int = 4,
               eps_loc: float = 0.,
               eps_scale: float = 0.,
               seed: int = 0) -> tfp.distributions.Mixture:
    """
    Defines a mixture of 'n_components' Normal distributions in 'n_dimensions' dimensions 
    with means and stddevs given by the tensors 'loc' and 'scale' with shapes 
    '(n_components,n_dimensions)'.
    The components are mixed according to the categorical distribution with probabilities
    'probs' (with shape equal to 'n_components'). This means that each component in all
    dimension is assigned a single probability.

    The resulting multivariate distribution has small correlation.

    Note: The functions 'MixNormal1' and 'MixNormal1_indep'
    generate identical samples, different from the samples generated by
    'MixNormal2' and 'MixNormal2_indep' (also identical).
    
    Args:
        n_components: int, number of components
        n_dimensions: int, number of dimensions
        seed: int, random seed

    Returns:    
        mix_gauss: tfp.distributions.MixtureSameFamily, mixture of Gaussians
    """
    reset_random_seeds(seed)
    loc: np.ndarray = np.random.sample([n_components, n_dimensions])*10
    loc_eps: np.ndarray = np.random.uniform(loc-eps_loc, loc+eps_loc)
    scale: np.ndarray = np.random.sample([n_components,n_dimensions])
    scale_eps: np.ndarray = np.random.uniform(scale-eps_scale, scale+eps_scale)
    probs: np.ndarray = np.random.sample(n_components)
    mix_gauss: tfp.distributions.MixtureSameFamily = tfp.distributions.MixtureSameFamily(
        mixture_distribution = tfp.distributions.Categorical(probs = probs),
        components_distribution = tfp.distributions.Normal(loc = loc_eps,
                                                           scale = scale_eps),
        validate_args = True)
    return mix_gauss

def MixNormal1_indep(n_components: int = 3,
                     n_dimensions: int = 4,
                     eps_loc: float = 0.,
                     eps_scale: float = 0.,
                     seed: int = 0) -> tfp.distributions.Independent:
    """
    Defines a mixture of 'n_components' Normal distributions in 'n_dimensions' dimensions 
    with means and stddevs given by the tensors 'loc' and 'scale' with shapes 
    '(n_components,n_dimensions)'.
    The components are mixed according to the categorical distribution with probabilities
    'probs' (with shape equal to that of 'loc' and 'scale'). This means that each component in each
    dimension can be assigned a different probability.

    The resulting multivariate distribution has small correlation.

    Note: The functions 'MixNormal1' and 'MixNormal1_indep'
    generate identical samples, different from the samples generated by
    'MixNormal2' and 'MixNormal2_indep' (also identical).
    
    Args:
        n_components: int, number of components
        n_dimensions: int, number of dimensions
        seed: int, random seed

    Returns:
        mix_gauss: tfp.distributions.Independent, mixture of Gaussians
    """
    reset_random_seeds(seed)
    loc: np.ndarray = np.random.sample([n_components, n_dimensions])*10
    loc_eps: np.ndarray = np.random.uniform(loc-eps_loc, loc+eps_loc)
    scale: np.ndarray = np.random.sample([n_components,n_dimensions])
    scale_eps: np.ndarray = np.random.uniform(scale-eps_scale, scale+eps_scale)
    probs: np.ndarray = np.random.sample([n_dimensions,n_components])
    components: List[tfp.distributions.Normal] = []
    for i in range(n_components):
        components.append(tfp.distributions.Normal(loc = loc_eps[i],
                                                   scale = scale_eps[i]))
    mix_gauss: tfp.distributions.Independent = tfp.distributions.Independent(
        distribution = tfp.distributions.Mixture(cat = tfp.distributions.Categorical(probs = probs),
                                   components = components,
                                   validate_args = True),
        reinterpreted_batch_ndims = 0)
    return mix_gauss
    
def MixNormal2_indep(n_components: int = 3,
                     n_dimensions: int = 4,
                     eps_loc: float = 0.,
                     eps_scale: float = 0.,
                     seed: int = 0) -> tfp.distributions.Independent:
    """
    Defines a mixture of 'n_components' Normal distributions in 'n_dimensions' dimensions 
    with means and stddevs given by the tensors 'loc' and 'scale' with shapes 
    '(n_components,n_dimensions)'.
    The components are mixed according to the categorical distribution with probabilities
    'probs' (with shape equal to 'n_components'). This means that each component in all
    dimension is assigned a single probability.

    The resulting multivariate distribution has small correlation.

    Note: The functions 'MixNormal1' and 'MixNormal1_indep'
    generate identical samples, different from the samples generated by
    'MixNormal2' and 'MixNormal2_indep' (also identical).
    
    Args:
        n_components: int, number of components
        n_dimensions: int, number of dimensions
        seed: int, random seed
        
    Returns:
        mix_gauss: tfp.distributions.Independent, mixture of Gaussians
    """
    reset_random_seeds(seed)
    loc: np.ndarray = np.random.sample([n_components, n_dimensions])*10
    loc_eps: np.ndarray = np.random.uniform(loc-eps_loc, loc+eps_loc)
    scale: np.ndarray = np.random.sample([n_components,n_dimensions])
    scale_eps: np.ndarray = np.random.uniform(scale-eps_scale, scale+eps_scale)
    probs: np.ndarray = np.random.sample(n_components)
    mix_gauss: tfp.distributions.Independent = tfp.distributions.Independent(
        distribution = tfp.distributions.MixtureSameFamily(
            mixture_distribution = tfp.distributions.Categorical(probs = probs),
            components_distribution = tfp.distributions.Normal(loc = loc_eps,
                                                               scale = scale_eps),
            validate_args = True),
        reinterpreted_batch_ndims = 0)
    return mix_gauss

def MixMultiNormal1(n_components: int = 3,
                    n_dimensions: int = 4,
                    eps_loc: float = 0.,
                    eps_scale: float = 0.,
                    seed: int = 0) -> tfp.distributions.Mixture:
    """
    Defines a mixture of 'n_components' Multivariate Normal distributions in 'n_dimensions' dimensions 
    with means and stddevs given by the tensors 'loc' and 'scale' with shapes 
    '(n_components,n_dimensions)'.
    The components are mixed according to the categorical distribution with probabilities
    'probs' (with shape equal to 'n_components'). This means that each Multivariate distribution 
    is assigned a single probability.

    The resulting multivariate distribution has large (random) correlation.

    Note: The functions 'MixMultiNormal1' and 'MixMultiNormal1_indep'
    generate identical samples, different from the samples generated by
    'MixMultiNormal2' and 'MixMultiNormal2_indep' (also identical).
    
    Args:
        n_components: int, number of components
        n_dimensions: int, number of dimensions
        seed: int, random seed
        
    Returns:
        mix_gauss: tfp.distributions.Mixture, mixture of Gaussians
    """
    reset_random_seeds(seed)
    loc: np.ndarray = np.random.sample([n_components, n_dimensions])*10
    loc_eps: np.ndarray = np.random.uniform(loc-eps_loc, loc+eps_loc)
    scale: np.ndarray = np.random.sample([n_components,n_dimensions])
    scale_eps: np.ndarray = np.random.uniform(scale-eps_scale, scale+eps_scale)
    probs: np.ndarray = np.random.sample(n_components)
    components: List[tfp.distributions.MultivariateNormalDiag] = []
    for i in range(n_components):
        components.append(tfp.distributions.MultivariateNormalDiag(loc = loc_eps[i],
                                                                   scale_diag = scale_eps[i]))
    mix_gauss: tfp.distributions.Mixture = tfp.distributions.Mixture(
        cat = tfp.distributions.Categorical(probs = probs),
        components = components,
        validate_args = True)
    return mix_gauss
    
def MixMultiNormal2(n_components: int = 3,
                    n_dimensions: int = 4,
                    eps_loc: float = 0.,
                    eps_scale: float = 0.,
                    seed: int = 0) -> tfp.distributions.MixtureSameFamily:
    """
    Defines a mixture of 'n_components' Multivariate Normal distributions in 'n_dimensions' dimensions 
    with means and stddevs given by the tensors 'loc' and 'scale' with shapes 
    '(n_components,n_dimensions)'.
    The components are mixed according to the categorical distribution with probabilities
    'probs' (with shape equal to 'n_components'). This means that each Multivariate distribution 
    is assigned a single probability.

    The resulting multivariate distribution has large (random) correlation.

    Note: The functions 'MixMultiNormal1' and 'MixMultiNormal1_indep'
    generate identical samples, different from the samples generated by
    'MixMultiNormal2' and 'MixMultiNormal2_indep' (also identical).
    
    Args:
        n_components: int, number of components
        n_dimensions: int, number of dimensions
        seed: int, random seed

    Returns:
        mix_gauss: tfp.distributions.MixtureSameFamily, mixture of Gaussians
    """
    reset_random_seeds(seed)
    loc: np.ndarray = np.random.sample([n_components, n_dimensions])*10
    loc_eps: np.ndarray = np.random.uniform(loc-eps_loc, loc+eps_loc)
    scale: np.ndarray = np.random.sample([n_components,n_dimensions])
    scale_eps: np.ndarray = np.random.uniform(scale-eps_scale, scale+eps_scale)
    probs = np.random.sample(n_components)
    mix_gauss: tfp.distributions.MixtureSameFamily = tfp.distributions.MixtureSameFamily(
        mixture_distribution = tfp.distributions.Categorical(probs = probs),
        components_distribution = tfp.distributions.MultivariateNormalDiag(loc = loc_eps,
                                                                           scale_diag = scale_eps),
        validate_args=True)
    return mix_gauss

def MixMultiNormal1_indep(n_components: int = 3,
                          n_dimensions: int = 4,
                          eps_loc: float = 0.,
                          eps_scale: float = 0.,
                          seed: int = 0) -> tfp.distributions.Independent:
    """
    Defines a mixture of 'n_components' Multivariate Normal distributions in 'n_dimensions' dimensions 
    with means and stddevs given by the tensors 'loc' and 'scale' with shapes 
    '(n_components,n_dimensions)'.
    The components are mixed according to the categorical distribution with probabilities
    'probs' (with shape equal to 'n_components'). This means that each Multivariate distribution 
    is assigned a single probability.

    The resulting multivariate distribution has large (random) correlation.

    Note: The functions 'MixMultiNormal1' and 'MixMultiNormal1_indep'
    generate identical samples, different from the samples generated by
    'MixMultiNormal2' and 'MixMultiNormal2_indep' (also identical).
    
    Args:
        n_components: int, number of components
        n_dimensions: int, number of dimensions
        seed: int, random seed

    Returns:
        mix_gauss: tfp.distributions.Independent, mixture of Gaussians
    """
    reset_random_seeds(seed)
    loc: np.ndarray = np.random.sample([n_components, n_dimensions])*10
    loc_eps: np.ndarray = np.random.uniform(loc-eps_loc, loc+eps_loc)
    scale: np.ndarray = np.random.sample([n_components,n_dimensions])
    scale_eps: np.ndarray = np.random.uniform(scale-eps_scale, scale+eps_scale)
    probs: np.ndarray = np.random.sample(n_components)
    components: List[tfp.distributions.MultivariateNormalDiag] = []
    for i in range(n_components):
        components.append(tfp.distributions.MultivariateNormalDiag(loc = loc_eps[i],
                                                                   scale_diag = scale_eps[i]))
    mix_gauss: tfp.distributions.Independent = tfp.distributions.Independent(
        distribution = tfp.distributions.Mixture(cat = tfp.distributions.Categorical(probs = probs),
                                                 components = components,
                                                 validate_args = True),
        reinterpreted_batch_ndims = 0)
    return mix_gauss
    
def MixMultiNormal2_indep(n_components: int = 3,
                          n_dimensions: int = 4,
                          eps_loc: float = 0.,
                          eps_scale: float = 0.,
                          seed: int = 0) -> tfp.distributions.Independent:
    """
    Defines a mixture of 'n_components' Multivariate Normal distributions in 'n_dimensions' dimensions 
    with means and stddevs given by the tensors 'loc' and 'scale' with shapes 
    '(n_components,n_dimensions)'.
    The components are mixed according to the categorical distribution with probabilities
    'probs' (with shape equal to 'n_components'). This means that each Multivariate distribution 
    is assigned a single probability.

    The resulting multivariate distribution has large (random) correlation.

    Note: The functions 'MixMultiNormal1' and 'MixMultiNormal1_indep'
    generate identical samples, different from the samples generated by
    'MixMultiNormal2' and 'MixMultiNormal2_indep' (also identical).
    
    Args:
        n_components: int, number of components
        n_dimensions: int, number of dimensions
        seed: int, random seed

    Returns:
        mix_gauss: tfp.distributions.Independent, mixture of Gaussians
    """
    reset_random_seeds(seed)
    loc: np.ndarray = np.random.sample([n_components, n_dimensions])*10
    loc_eps: np.ndarray = np.random.uniform(loc-eps_loc, loc+eps_loc)
    scale: np.ndarray = np.random.sample([n_components,n_dimensions])
    scale_eps: np.ndarray = np.random.uniform(scale-eps_scale, scale+eps_scale)
    probs: np.ndarray = np.random.sample(n_components)

    mix_gauss: tfp.distributions.Independent = tfp.distributions.Independent(
        distribution = tfp.distributions.MixtureSameFamily(
            mixture_distribution = tfp.distributions.Categorical(probs = probs),
            components_distribution = tfp.distributions.MultivariateNormalDiag(loc = loc_eps,
                                                                               scale_diag = scale_eps),
            validate_args = True),
        reinterpreted_batch_ndims = 0)
    return mix_gauss

#def generate_random_correlation_matrix(n, seed=0):
#    reset_random_seeds(seed)  
#    A = np.random.randn(n, n)
#    A = (A + A.T) / 2
#    A = np.dot(A, A.T)
#    D = np.sqrt(np.diag(1 / np.diag(A)))
#    correlation_matrix = np.dot(D, np.dot(A, D))
#    return correlation_matrix

#def generate_random_correlation_matrix(n, seed=0):
#    if seed is not None:
#        np.random.seed(seed)
#    A = np.random.normal(size=(n, n))
#    B = np.dot(A, A.T)
#    D = np.sqrt(np.diag(B))
#    correlation_matrix = B / np.outer(D, D)
#    return correlation_matrix

def generate_random_correlation_matrix(n, 
                                       seed = 0,
                                       n_samples = 50_000):
    reset_random_seeds(seed)
    mix = MixtureGaussian(3, n, 0., 0., seed)
    samp = mix.sample(n_samples).numpy()
    df = pd.DataFrame(samp)
    corr = df.corr().to_numpy()
    return corr

def MultiNormal1(n_dimensions: int = 4,
                 eps_loc: float = 0.,
                 eps_scale: float = 0.,
                 seed: int = 0
                ) -> tfp.distributions.MultivariateNormalTriL:
    reset_random_seeds(seed)
    loc: np.ndarray = np.random.sample(n_dimensions) * 10
    loc_eps_np: np.ndarray = np.random.uniform(loc - eps_loc, loc + eps_loc)
    loc_eps: tf.Tensor = tf.constant(loc_eps_np, dtype = tf.float32)
    correlation_matrix_np: np.ndarray = generate_random_correlation_matrix(n_dimensions, seed = seed)
    correlation_matrix: tf.Tensor = tf.constant(correlation_matrix_np * eps_scale, dtype = tf.float32)
    scale_eps: tf.Tensor = tf.linalg.cholesky(correlation_matrix) # type: ignore
    mvn = tfp.distributions.MultivariateNormalTriL(loc = loc_eps, 
                                                   scale_tril = scale_eps)
    return mvn

def describe_distributions(distributions: List[tfp.distributions.Distribution]) -> None:
    """
    Describes a 'tfp.distributions' object.
    
    Args:
        distributions: list of 'tfp.distributions' objects, distributions to describe

    Returns:
        None (prints the description)
    """
    print('\n'.join([str(d) for d in distributions]))

def rot_matrix(data: np.ndarray) -> np.ndarray:
    """
    Calculates the matrix that rotates the covariance matrix of 'data' to the diagonal basis.

    Args:
        data: np.ndarray, data to rotate

    Returns:
        rotation: np.ndarray, rotation matrix
    """
    cov_matrix: np.ndarray = np.cov(data, rowvar=False)
    w: np.ndarray
    V: np.ndarray
    w, V = np.linalg.eig(cov_matrix)
    return V

def transform_data(data: np.ndarray,
                   rotation: np.ndarray) -> np.ndarray:
    """
    Transforms the data according to the rotation matrix 'rotation'.
    
    Args:
        data: np.ndarray, data to transform
        rotation: np.ndarray, rotation matrix

    Returns:
        data_new: np.ndarray, transformed data
    """
    if len(rotation.shape) != 2:
        raise ValueError('Rottion matrix must be a 2D matrix.')
    elif rotation.shape[0] != rotation.shape[1]:
        raise ValueError('Rotation matrix must be square.')
    data_new: np.ndarray = np.dot(data,rotation)
    return data_new

def inverse_transform_data(data: np.ndarray,
                           rotation: np.ndarray) -> np.ndarray:
    """
    Transforms the data according to the inverse of the rotation matrix 'rotation'.
    
    Args:
        data: np.ndarray, data to transform
        rotation: np.ndarray, rotation matrix
        
    Returns:
        data_new: np.ndarray, transformed data
    """
    if len(rotation.shape) != 2:
        raise ValueError('Rottion matrix must be a 2D matrix.')
    elif rotation.shape[0] != rotation.shape[1]:
        raise ValueError('Rotation matrix must be square.')
    data_new: np.ndarray = np.dot(data,np.transpose(rotation))
    return data_new

def reset_random_seeds(seed: int = 0) -> None:
    """
    Resets the random seeds of the packages 'tensorflow', 'numpy' and 'random'.
    
    Args:
        seed: int, random seed
        
    Returns:
        None
    """
    os.environ['PYTHONHASHSEED'] = str(seed)
    tf.random.set_seed(seed)
    np.random.seed(seed)
    random.seed(seed)

def RandCorr(matrixSize: int,
             seed: int) -> np.ndarray:
    """
    Generates a random correlation matrix of size 'matrixSize' x 'matrixSize'.

    Args:
        matrixSize: int, size of the matrix
        seed: int, random seed
        
    Returns:
        Vnorm: np.ndarray, normalized random correlation matrix
    """
    np.random.seed(0)
    V: np.ndarray = sklearn.datasets.make_spd_matrix(matrixSize,
                                                     random_state = seed)
    D: np.ndarray = np.sqrt(np.diag(np.diag(V)))
    Dinv: np.ndarray = np.linalg.inv(D)
    Vnorm: np.ndarray = np.matmul(np.matmul(Dinv,V),Dinv)
    return Vnorm

def is_pos_def(x: np.ndarray) -> bool:
    """ 
    Checks if the matrix 'x' is positive definite.
    
    Args:
        x: np.ndarray, matrix to check

    Returns:
        bool, True if 'x' is positive definite, False otherwise
    """
    if len(x.shape) != 2:
        raise ValueError('Input to is_pos_def must be a 2-dimensional array.')
    elif x.shape[0] != x.shape[1]:
        raise ValueError('Input to is_pos_def must be a square matrix.')
    return bool(np.all(np.linalg.eigvals(x) > 0))

def RandCov(std: np.ndarray,
            seed: int) -> np.ndarray:
    """
    Generates a random covariance matrix of size 'matrixSize' x 'matrixSize'.

    Args:
        std: np.ndarray, standard deviations of the random variables
        seed: int, random seed
        
    Returns:
        V: np.ndarray, random covariance matrix
    """
    matrixSize: int = len(std)
    corr: np.ndarray = RandCorr(matrixSize,seed)
    D: np.ndarray = np.diag(std)
    V: np.ndarray = np.matmul(np.matmul(D,corr),D)
    return V