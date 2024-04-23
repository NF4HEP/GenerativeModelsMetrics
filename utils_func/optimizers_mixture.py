__all__ = [
    'compute_exclusion_adaptive_bisection',
    'compute_exclusion_bisection',
    'compute_exclusion_LR_adaptive_bisection',
    'compute_exclusion_LR_bisection'
]
import os
import sys
from datetime import datetime
import numpy as np
import json
from scipy.stats import moment # type: ignore
import tensorflow as tf
import tensorflow_probability as tfp
from timeit import default_timer as timer

sys.path.insert(0,'../utils_func/')
import MixtureDistributions # type: ignore
sys.path.insert(0,'../')
import GMetrics # type: ignore
from GMetrics.utils import save_update_metrics_config, save_update_LR_metrics_config # type: ignore

from typing import Tuple, Union, Optional, Type, Callable, Dict, List, Any
from numpy import typing as npt
DTypeType = Union[tf.DType, np.dtype, type]
IntTensor = Type[tf.Tensor]
FloatTensor = Type[tf.Tensor]
BoolTypeTF = Type[tf.Tensor]
BoolTypeNP = np.bool_
IntType = Union[int, IntTensor]
DataTypeTF = FloatTensor
DataTypeNP = npt.NDArray[np.float_]
DataType = Union[DataTypeNP, DataTypeTF]
DistTypeTF = tfp.distributions.Distribution

def compute_exclusion_adaptive_bisection(metric_config: Dict[str,Any],
                                         test_kwargs: Dict[str,Any],
                                         model_dir: str,
                                         deformation: str = "mean", # could be mean, std, or both
                                         seed_dist: int = 0,
                                         x_tol: float = 0.01,
                                         fn_tol: float = 0.01,
                                         eps_min: float = 0.,
                                         eps_max: float = 1.,
                                         initial_division_factor: float = 1 / 2.,
                                         reduce_division_factor: float = 1.,
                                         max_iterations: int = 100,
                                         save: bool = True,
                                         verbose: bool = True
                                        ) -> Dict[str,Any]:
    # Generate timestamp for result
    timestamp: str = datetime.now().isoformat()
    
    if verbose:
        print("\n======================================================")
    if deformation == "mean":
        if verbose:
            print(f"=============== {metric_config['name']} - only mean ===============")
    elif deformation == "std":
        if verbose:
            print(f"=============== {metric_config['name']} - only std ===============")
    elif deformation == "both":
        if verbose:
            print(f"=============== {metric_config['name']} - mean+std ===============")
    else:
        raise ValueError(f"Invalid value for mean_std_both: {deformation}")
    if verbose:
        print("======================================================") 
    
    # Define metric name:
    metric_name = metric_config["name"]
    metric_class = eval(metric_config["class_name"])
    metric_kwargs = metric_config["kwargs"]
    metric_result_key = metric_config["result_key"]
    metric_scale_func = metric_config["scale_func"]
    max_vectorize = metric_config["max_vectorize"]
    
    # Define ncomp and ndims
    ncomp = metric_config["test_config"]["ncomp"]
    ndims = metric_config["test_config"]["ndims"]
    
    # Compute metric scaling factor
    nsamples = test_kwargs["batch_size_test"]
    ns = nsamples**2 / (2 * nsamples)

    metrics_list = []
    eps_list = []
    exclusion_list = []

    metric_thresholds = metric_config["thresholds"][-2:]
    metric_threshold_number = 0
    eps_min_start = eps_min
    eps_max_start = eps_max
    division_factor = initial_division_factor
    initial_relative_error_eps = 2 * (eps_max - eps_min) / (eps_max + eps_min)
    relative_error_eps_threshold = initial_relative_error_eps
    initial_relative_error_metric = 2 * (eps_max - eps_min) / (eps_max + eps_min)
    relative_error_metric_threshold = initial_relative_error_metric
    eps = (eps_max + eps_min) / 2.

    start_global = timer()
    start = timer()
    
    dist_1 = MixtureDistributions.MixtureGaussian(ncomp, ndims, 0., 0., seed_dist)

    iteration = 0

    while metric_threshold_number < len(metric_thresholds) and iteration < max_iterations:
        iteration += 1
        
        if deformation == "mean":
            eps_mean = eps
            eps_std = 0.
        elif deformation == "std":
            eps_mean = 0.
            eps_std = eps
        else:
            eps_mean = eps
            eps_std = eps
        
        print(f"\n------------ {iteration} ------------")
        print(f"eps = {eps}")
        
        dist_2 = MixtureDistributions.MixtureGaussian(ncomp, ndims, eps_mean, eps_std, seed_dist)

        TwoSampleTestInputs = GMetrics.TwoSampleTestInputs(dist_1_input = dist_1,
                                                           dist_2_input = dist_2,
                                                           **test_kwargs)

        Metric = metric_class(TwoSampleTestInputs, **metric_kwargs) # type: ignore
        Metric.Test_tf(max_vectorize=max_vectorize)
        metric = np.mean(Metric.Results[-1].result_value[metric_result_key]) * metric_scale_func(ns, ndims) # type: ignore

        metrics_list.append(metric)
        eps_list.append(eps)

        # Determine direction of adjustment based on overshooting or undershooting
        if metric > metric_thresholds[metric_threshold_number][2]: # type: ignore
            #direction = -1
            eps_max = eps  # Update the maximum bound
            eps = eps_max - (eps_max - eps_min) * division_factor
        else:
            #direction = 1
            eps_min = eps  # Update the minimum bound
            eps = eps_min + (eps_max - eps_min) * division_factor
                        
        if verbose:
            print(f"statistic = {metric} - next threshold = {metric_thresholds[metric_threshold_number][2]} at {metric_thresholds[metric_threshold_number][0]} CL")

        relative_error_eps = 2 * (eps_max - eps_min) / (eps_max + eps_min)
        relative_error_metric = 2 * np.abs(metric_thresholds[metric_threshold_number][2] - metric) / (metric_thresholds[metric_threshold_number][2] + metric)
        if verbose:
            print(f"relative_error_eps = {relative_error_eps}")
            print(f"relative_error_metric = {relative_error_metric}")

        if division_factor / reduce_division_factor <= 1 / 2.:
            division_factor = 1 / 2.
        else:
            if relative_error_eps < relative_error_eps_threshold  / 2 and relative_error_metric < relative_error_metric_threshold / 2:
                print(f"Relative error halved. Reducing division factor from {division_factor} to {division_factor / reduce_division_factor}")
                relative_error_eps_threshold = relative_error_eps
                relative_error_metric_threshold = relative_error_metric
                division_factor = division_factor / reduce_division_factor
            
        
        # Check if the fn value is within the required accuracy of the threshold
        if relative_error_eps < x_tol and relative_error_metric < fn_tol:
            end = timer()
            if verbose:
                print(f"=======> statistic within required accuracy at {metric_thresholds[metric_threshold_number][0]} CL in {end - start} seconds")
            exclusion_list.append([metric_thresholds[metric_threshold_number][0], metric_name, eps, metric, end - start])
            metric_threshold_number += 1
            print("\n======================================================")
            print("New threshold. Resetting eps_min and eps_max.")
            start = timer() # Reset the timer
            iteration = 0
            eps_min, eps_max = eps, eps_max_start # Initialize the bounds
            division_factor = initial_division_factor
            relative_error_eps_threshold = initial_relative_error_eps
            relative_error_metric_threshold = initial_relative_error_metric
        
    end = timer()
    if verbose:
        print("Time elapsed:", end - start_global, "seconds.")
    result = {timestamp: {"test_config": test_kwargs,
                          "null_config": metric_config,
                          "deformation": deformation,
                          "parameters": {"ncomp": ncomp,
                                         "seed_dist": seed_dist,
                                         "x_tol": x_tol,
                                         "fn_tol": fn_tol,
                                         "eps_min": eps_min_start,
                                         "eps_max": eps_max_start,
                                         "max_iterations": max_iterations,
                                         "save": save,
                                         "verbose": verbose},
                          "exclusion_list": exclusion_list,
                          "eps_list": eps_list,
                          "metrics_list": metrics_list,
                          "time_elapsed": end - start_global}}
    
    # Saving if required
    if save:
        file_path = model_dir + "exclusion_limits.json"
        if verbose:
            print(f"Saving results in the file {file_path}")
        # Step 1: Read the existing content if the file exists
        existing_data = {}
        if os.path.exists(file_path):
            try:
                with open(file_path, "r") as file:
                    existing_data = json.load(file)
            except json.JSONDecodeError:
                # File is empty or corrupted, start with an empty dictionary
                existing_data = {}
        
        # Step 2: Update the dictionary with new results
        existing_data.update(result)
        
        # Step 3: Write the updated dictionary back to the file
        # Use this custom encoder when dumping your JSON data
        with open(file_path, "w") as file:
            json.dump(existing_data, file, cls=GMetrics.utils.CustomEncoder, indent=4) # type: ignore
    
    return result

def compute_exclusion_bisection(metric_config: Dict[str,Any],
                                test_kwargs: Dict[str,Any],
                                model_dir: str,
                                deformation: str = "mean", # could be mean, std, or both
                                seed_dist: int = 0,
                                x_tol: float = 0.01,
                                fn_tol: float = 0.01,
                                eps_min: float = 0.,
                                eps_max: float = 1.,
                                max_iterations: int = 100,
                                save: bool = True,
                                verbose: bool = True
                               ) -> Dict[str,Any]:
    # Generate timestamp for result
    timestamp: str = datetime.now().isoformat()
    
    if verbose:
        print("\n======================================================")
    if deformation == "mean":
        if verbose:
            print(f"=============== {metric_config['name']} - only mean ===============")
    elif deformation == "std":
        if verbose:
            print(f"=============== {metric_config['name']} - only std ===============")
    elif deformation == "both":
        if verbose:
            print(f"=============== {metric_config['name']} - mean+std ===============")
    else:
        raise ValueError(f"Invalid value for mean_std_both: {deformation}")
    if verbose:
        print("======================================================") 
    
    # Define metric name:
    metric_name = metric_config["name"]
    metric_class = eval(metric_config["class_name"])
    metric_kwargs = metric_config["kwargs"]
    metric_result_key = metric_config["result_key"]
    metric_scale_func = metric_config["scale_func"]
    max_vectorize = metric_config["max_vectorize"]
    
    # Define ncomp and ndims
    ncomp = metric_config["test_config"]["ncomp"]
    ndims = metric_config["test_config"]["ndims"]
    
    # Compute metric scaling factor
    nsamples = test_kwargs["batch_size_test"]
    ns = nsamples**2 / (2 * nsamples)

    metrics_list = []
    eps_list = []
    exclusion_list = []

    metric_thresholds = metric_config["thresholds"][-2:]
    metric_threshold_number = 0
    eps_min_start = eps_min
    eps_max_start = eps_max
    eps = (eps_max + eps_min) / 2.

    start_global = timer()
    start = timer()
    
    dist_1 = MixtureDistributions.MixtureGaussian(ncomp, ndims, 0., 0., seed_dist)

    iteration = 0

    while metric_threshold_number < len(metric_thresholds) and iteration < max_iterations:
        iteration += 1
        
        if deformation == "mean":
            eps_mean = eps
            eps_std = 0.
        elif deformation == "std":
            eps_mean = 0.
            eps_std = eps
        else:
            eps_mean = eps
            eps_std = eps
        
        print(f"\n------------ {iteration} ------------")
        print(f"eps = {eps}")
        
        dist_2 = MixtureDistributions.MixtureGaussian(ncomp, ndims, eps_mean, eps_std, seed_dist)

        TwoSampleTestInputs = GMetrics.TwoSampleTestInputs(dist_1_input = dist_1,
                                                           dist_2_input = dist_2,
                                                           **test_kwargs)

        Metric = metric_class(TwoSampleTestInputs, **metric_kwargs) # type: ignore
        Metric.Test_tf(max_vectorize=max_vectorize)
        metric = np.mean(Metric.Results[-1].result_value[metric_result_key]) * metric_scale_func(ns, ndims) # type: ignore

        metrics_list.append(metric)
        eps_list.append(eps)

        # Determine direction of adjustment based on overshooting or undershooting
        if metric > metric_thresholds[metric_threshold_number][2]: # type: ignore
            #direction = -1
            eps_max = eps  # Update the maximum bound
            eps = eps_max - (eps_max - eps_min) / 2.
        else:
            #direction = 1
            eps_min = eps  # Update the minimum bound
            eps = eps_min + (eps_max - eps_min) / 2.
                        
        if verbose:
            print(f"statistic = {metric} - next threshold = {metric_thresholds[metric_threshold_number][2]} at {metric_thresholds[metric_threshold_number][0]} CL")

        relative_error_eps = 2 * (eps_max - eps_min) / (eps_max + eps_min)
        relative_error_metric = 2 * np.abs(metric_thresholds[metric_threshold_number][2] - metric) / (metric_thresholds[metric_threshold_number][2] + metric)
        if verbose:
            print(f"relative_error_eps = {relative_error_eps}")
            print(f"relative_error_metric = {relative_error_metric}")
        
        # Check if the fn value is within the required accuracy of the threshold
        if relative_error_eps < x_tol and relative_error_metric < fn_tol:
            end = timer()
            if verbose:
                print(f"=======> statistic within required accuracy at {metric_thresholds[metric_threshold_number][0]} CL in {end - start} seconds")
            exclusion_list.append([metric_thresholds[metric_threshold_number][0], metric_name, eps, metric, end - start])
            metric_threshold_number += 1
            print("\n======================================================")
            print("New threshold. Resetting eps_min and eps_max.")
            start = timer() # Reset the timer
            iteration = 0
            eps_min, eps_max = eps, eps_max_start # Initialize the bounds
        
    end = timer()
    if verbose:
        print("Time elapsed:", end - start_global, "seconds.")
    result = {timestamp: {"test_config": test_kwargs,
                          "null_config": metric_config,
                          "deformation": deformation,
                          "parameters": {"ncomp": ncomp,
                                         "seed_dist": seed_dist,
                                         "x_tol": x_tol,
                                         "fn_tol": fn_tol,
                                         "eps_min": eps_min_start,
                                         "eps_max": eps_max_start,
                                         "max_iterations": max_iterations,
                                         "save": save,
                                         "verbose": verbose},
                          "exclusion_list": exclusion_list,
                          "eps_list": eps_list,
                          "metrics_list": metrics_list,
                          "time_elapsed": end - start_global}}
    
    # Saving if required
    if save:
        file_path = model_dir + "exclusion_limits.json"
        if verbose:
            print(f"Saving results in the file {file_path}")
        # Step 1: Read the existing content if the file exists
        existing_data = {}
        if os.path.exists(file_path):
            try:
                with open(file_path, "r") as file:
                    existing_data = json.load(file)
            except json.JSONDecodeError:
                # File is empty or corrupted, start with an empty dictionary
                existing_data = {}
        
        # Step 2: Update the dictionary with new results
        existing_data.update(result)
        
        # Step 3: Write the updated dictionary back to the file
        # Use this custom encoder when dumping your JSON data
        with open(file_path, "w") as file:
            json.dump(existing_data, file, cls=GMetrics.utils.CustomEncoder, indent=4) # type: ignore
    
    return result


def compute_exclusion_LR_adaptive_bisection(metric_config: Dict[str,Any],
                                            test_kwargs: Dict[str,Any],
                                            model_dir: str,
                                            cl_list = [0.95, 0.99],
                                            deformation: str = "mean", # could be mean, std, or both
                                            seed_dist: int = 0,
                                            x_tol: float = 0.01,
                                            fn_tol: float = 0.01,
                                            eps_min: float = 0.,
                                            eps_max: float = 1.,
                                            initial_division_factor: float = 1 / 2.,
                                            reduce_division_factor: float = 1.,
                                            max_iterations: int = 100,
                                            save: bool = True,
                                            verbose: bool = True
                                           ) -> Dict[str,Any]:
    # Generate timestamp for result
    timestamp: str = datetime.now().isoformat()
    
    if verbose:
        print("\n======================================================")
    if deformation == "mean":
        if verbose:
            print(f"=============== {metric_config['name']} - only mean ===============")
    elif deformation == "std":
        if verbose:
            print(f"=============== {metric_config['name']} - only std ===============")
    elif deformation == "both":
        if verbose:
            print(f"=============== {metric_config['name']} - mean+std ===============")
    else:
        raise ValueError(f"Invalid value for mean_std_both: {deformation}")
    if verbose:
        print("======================================================")
        
    test_kwargs_null = dict(test_kwargs)
    test_kwargs_alt = dict(test_kwargs)
    test_kwargs_alt["niter"] = 10
    
    metric_kwargs_null = dict(metric_config["kwargs"])
    metric_kwargs_alt = dict(metric_config["kwargs"])
    metric_kwargs_null["null_test"] = True
    metric_kwargs_alt["null_test"] = False
    #metric_kwargs_null["verbose"] = True
    #metric_kwargs_alt["verbose"] = True
    
    metric_name = metric_config["name"]
    metric_result_key = metric_config["result_key"]
    metric_scale_func = metric_config["scale_func"]
    max_vectorize = metric_config["max_vectorize"]
    null_file_base = metric_config["null_file"]
    metrics_config_file = model_dir + "metrics_config.json"
    
    # Define ncomp and ndims
    ncomp = metric_config["test_config"]["ncomp"]
    ndims = metric_config["test_config"]["ndims"]
    
    # Compute metric scaling factor
    nsamples = test_kwargs["batch_size_test"]
    ns = nsamples**2 / (2 * nsamples)
    
    metrics_list = []
    eps_list = []
    exclusion_list = []
    
    metric_threshold_number = 0
    eps_min_start = eps_min
    eps_max_start = eps_max
    division_factor = initial_division_factor
    initial_relative_error_eps = 2 * (eps_max - eps_min) / (eps_max + eps_min)
    relative_error_eps_threshold = initial_relative_error_eps
    initial_relative_error_metric = 2 * (eps_max - eps_min) / (eps_max + eps_min)
    relative_error_metric_threshold = initial_relative_error_metric
    eps = (eps_max + eps_min) / 2.
    
    start_global = timer()
    start = timer()
    
    dist_1 = MixtureDistributions.MixtureGaussian(ncomp, ndims, 0., 0., seed_dist)

    iteration = 0

    while metric_threshold_number < len(cl_list) and iteration < max_iterations:
        iteration += 1

        if deformation == "mean":
            eps_mean = eps
            eps_std = 0.
        elif deformation == "std":
            eps_mean = 0.
            eps_std = eps
        else:
            eps_mean = eps
            eps_std = eps
            
        print(f"\n------------ {iteration} ------------")
        print(f"eps = {eps}")

        print(f"Computing null distribution")
        start_null = timer()
        dist_2 = MixtureDistributions.MixtureGaussian(ncomp, ndims, eps_mean, eps_std, seed_dist)
        
        TwoSampleTestInputs = GMetrics.TwoSampleTestInputs(dist_1_input = dist_1,
                                                           dist_2_input = dist_2,
                                                           **test_kwargs_null)
        
        LRMetric_null = GMetrics.LRMetric(TwoSampleTestInputs, **metric_kwargs_null)
        LRMetric_null.Test_tf(max_vectorize = max_vectorize)
        
        null_file = null_file_base.replace(".json", "_" + deformation + "_" + str(format(eps, '.6f')) + ".json")
        print("Saving", metric_name, "to", null_file)
        LRMetric_null.Results.save_to_json(null_file)
        
        dist_null = np.array(LRMetric_null.Results[-1].result_value[metric_result_key]) * metric_scale_func(ns, ndims)
        metric_thresholds = [[cl, 
                              [int(cl*len(dist_null)), 
                               int((1-cl)*len(dist_null))], 
                              np.sort(dist_null)[int(len(dist_null)*cl)]] for cl in cl_list]
        print(f"ThresholdS: {metric_thresholds}")
        metric_config["thresholds"].append([eps, deformation, metric_thresholds])
        save_update_LR_metrics_config(metric_config = metric_config, 
                                      metrics_config_file = metrics_config_file) # type: ignore
        end_null = timer()
        print(f"Null distribution computed in {end_null - start_null} seconds")
        
        print(f"Evaluating alternative distribution")
        TwoSampleTestInputs = GMetrics.TwoSampleTestInputs(dist_1_input = dist_1,
                                                           dist_2_input = dist_2,
                                                           **test_kwargs_alt)
        LRMetric_alt = GMetrics.LRMetric(TwoSampleTestInputs, **metric_kwargs_alt)
        LRMetric_alt.Test_tf(max_vectorize = max_vectorize)
        metric = np.mean(LRMetric_alt.Results[-1].result_value[metric_result_key]) * metric_scale_func(ns, ndims) # type: ignore
        
        metrics_list.append(metric)
        eps_list.append(eps)

        # Determine direction of adjustment based on overshooting or undershooting
        if metric > metric_thresholds[metric_threshold_number][2]: # type: ignore
            #direction = -1
            eps_max = eps  # Update the maximum bound
            eps = eps_max - (eps_max - eps_min) * division_factor
        else:
            #direction = 1
            eps_min = eps  # Update the minimum bound
            eps = eps_min + (eps_max - eps_min) * division_factor
                        
        if verbose:
            print(f"statistic = {metric} - next threshold = {metric_thresholds[metric_threshold_number][2]} at {metric_thresholds[metric_threshold_number][0]} CL")

        relative_error_eps = 2 * (eps_max - eps_min) / (eps_max + eps_min)
        relative_error_metric = 2 * np.abs(metric_thresholds[metric_threshold_number][2] - metric) / (metric_thresholds[metric_threshold_number][2] + metric)
        if verbose:
            print(f"relative_error_eps = {relative_error_eps}")
            print(f"relative_error_metric = {relative_error_metric}")

        if division_factor / reduce_division_factor <= 1 / 2.:
            division_factor = 1 / 2.
        else:
            if relative_error_eps < relative_error_eps_threshold  / 2 and relative_error_metric < relative_error_metric_threshold / 2:
                print(f"Relative error halved. Reducing division factor from {division_factor} to {division_factor / reduce_division_factor}")
                relative_error_eps_threshold = relative_error_eps
                relative_error_metric_threshold = relative_error_metric
                division_factor = division_factor / reduce_division_factor
            
        
        # Check if the fn value is within the required accuracy of the threshold
        if relative_error_eps < x_tol and relative_error_metric < fn_tol:
            end = timer()
            if verbose:
                print(f"=======> statistic within required accuracy at {metric_thresholds[metric_threshold_number][0]} CL in {end - start} seconds")
            exclusion_list.append([metric_thresholds[metric_threshold_number][0], metric_name, eps, metric, end - start])
            metric_threshold_number += 1
            print("\n======================================================")
            print("New threshold. Resetting eps_min and eps_max.")
            start = timer() # Reset the timer
            iteration = 0
            eps_min, eps_max = eps, eps_max_start # Initialize the bounds
            division_factor = initial_division_factor
            relative_error_eps_threshold = initial_relative_error_eps
            relative_error_metric_threshold = initial_relative_error_metric
            
    end = timer()
    if verbose:
        print("Time elapsed:", end - start_global, "seconds.")
    result = {timestamp: {"test_config": test_kwargs,
                          "null_config": metric_config,
                          "deformation": deformation,
                          "parameters": {"ncomp": ncomp,
                                         "seed_dist": seed_dist,
                                         "x_tol": x_tol,
                                         "fn_tol": fn_tol,
                                         "eps_min": eps_min_start,
                                         "eps_max": eps_max_start,
                                         "max_iterations": max_iterations,
                                         "save": save,
                                         "verbose": verbose},
                          "exclusion_list": exclusion_list,
                          "eps_list": eps_list,
                          "metrics_list": metrics_list,
                          "time_elapsed": end - start_global}}
    
    # Saving if required
    if save:
        file_path = model_dir + "exclusion_limits.json"
        if verbose:
            print(f"Saving results in the file {file_path}")
        # Step 1: Read the existing content if the file exists
        existing_data = {}
        if os.path.exists(file_path):
            try:
                with open(file_path, "r") as file:
                    existing_data = json.load(file)
            except json.JSONDecodeError:
                # File is empty or corrupted, start with an empty dictionary
                existing_data = {}
        
        # Step 2: Update the dictionary with new results
        existing_data.update(result)
        
        # Step 3: Write the updated dictionary back to the file
        # Use this custom encoder when dumping your JSON data
        with open(file_path, "w") as file:
            json.dump(existing_data, file, cls=GMetrics.utils.CustomEncoder, indent=4) # type: ignore
    
    return result

def compute_exclusion_LR_bisection(metric_config: Dict[str,Any],
                                   test_kwargs: Dict[str,Any],
                                   model_dir: str,
                                   cl_list = [0.95, 0.99],
                                   deformation: str = "mean", # could be mean, std, or both
                                   seed_dist: int = 0,
                                   x_tol: float = 0.01,
                                   fn_tol: float = 0.01,
                                   eps_min: float = 0.,
                                   eps_max: float = 1.,
                                   max_iterations: int = 100,
                                   save: bool = True,
                                   verbose: bool = True
                                  ) -> Dict[str,Any]:
    # Generate timestamp for result
    timestamp: str = datetime.now().isoformat()
    
    if verbose:
        print("\n======================================================")
    if deformation == "mean":
        if verbose:
            print(f"=============== {metric_config['name']} - only mean ===============")
    elif deformation == "std":
        if verbose:
            print(f"=============== {metric_config['name']} - only std ===============")
    elif deformation == "both":
        if verbose:
            print(f"=============== {metric_config['name']} - mean+std ===============")
    else:
        raise ValueError(f"Invalid value for mean_std_both: {deformation}")
    if verbose:
        print("======================================================")
        
    test_kwargs_null = dict(test_kwargs)
    test_kwargs_alt = dict(test_kwargs)
    test_kwargs_alt["niter"] = 10
    
    metric_kwargs_null = dict(metric_config["kwargs"])
    metric_kwargs_alt = dict(metric_config["kwargs"])
    metric_kwargs_null["null_test"] = True
    metric_kwargs_alt["null_test"] = False
    #metric_kwargs_null["verbose"] = True
    #metric_kwargs_alt["verbose"] = True
    
    metric_name = metric_config["name"]
    metric_result_key = metric_config["result_key"]
    metric_scale_func = metric_config["scale_func"]
    max_vectorize = metric_config["max_vectorize"]
    null_file_base = metric_config["null_file"]
    metrics_config_file = model_dir + "metrics_config.json"
    
    # Define ncomp and ndims
    ncomp = metric_config["test_config"]["ncomp"]
    ndims = metric_config["test_config"]["ndims"]
    
    # Compute metric scaling factor
    nsamples = test_kwargs["batch_size_test"]
    ns = nsamples**2 / (2 * nsamples)
    
    metrics_list = []
    eps_list = []
    exclusion_list = []
    
    metric_threshold_number = 0
    eps_min_start = eps_min
    eps_max_start = eps_max
    eps = (eps_max + eps_min) / 2.
    
    start_global = timer()
    start = timer()
    
    dist_1 = MixtureDistributions.MixtureGaussian(ncomp, ndims, 0., 0., seed_dist)

    iteration = 0

    while metric_threshold_number < len(cl_list) and iteration < max_iterations:
        iteration += 1

        if deformation == "mean":
            eps_mean = eps
            eps_std = 0.
        elif deformation == "std":
            eps_mean = 0.
            eps_std = eps
        else:
            eps_mean = eps
            eps_std = eps
            
        print(f"\n------------ {iteration} ------------")
        print(f"eps = {eps}")

        print(f"Computing null distribution")
        start_null = timer()
        dist_2 = MixtureDistributions.MixtureGaussian(ncomp, ndims, eps_mean, eps_std, seed_dist)
        
        TwoSampleTestInputs = GMetrics.TwoSampleTestInputs(dist_1_input = dist_1,
                                                           dist_2_input = dist_2,
                                                           **test_kwargs_null)
        
        LRMetric_null = GMetrics.LRMetric(TwoSampleTestInputs, **metric_kwargs_null)
        LRMetric_null.Test_tf(max_vectorize = max_vectorize)
        
        null_file = null_file_base.replace(".json", "_" + deformation + "_" + str(format(eps, '.6f')) + ".json")
        print("Saving", metric_name, "to", null_file)
        LRMetric_null.Results.save_to_json(null_file)
        
        dist_null = np.array(LRMetric_null.Results[-1].result_value[metric_result_key]) * metric_scale_func(ns, ndims)
        metric_thresholds = [[cl, 
                              [int(cl*len(dist_null)), 
                               int((1-cl)*len(dist_null))], 
                              np.sort(dist_null)[int(len(dist_null)*cl)]] for cl in cl_list]
        print(f"ThresholdS: {metric_thresholds}")
        metric_config["thresholds"].append([eps, deformation, metric_thresholds])
        save_update_LR_metrics_config(metric_config = metric_config, 
                                      metrics_config_file = metrics_config_file) # type: ignore
        end_null = timer()
        print(f"Null distribution computed in {end_null - start_null} seconds")
        
        print(f"Evaluating alternative distribution")
        TwoSampleTestInputs = GMetrics.TwoSampleTestInputs(dist_1_input = dist_1,
                                                           dist_2_input = dist_2,
                                                           **test_kwargs_alt)
        LRMetric_alt = GMetrics.LRMetric(TwoSampleTestInputs, **metric_kwargs_alt)
        LRMetric_alt.Test_tf(max_vectorize = max_vectorize)
        metric = np.mean(LRMetric_alt.Results[-1].result_value[metric_result_key]) * metric_scale_func(ns, ndims) # type: ignore
        
        metrics_list.append(metric)
        eps_list.append(eps)

        # Determine direction of adjustment based on overshooting or undershooting
        if metric > metric_thresholds[metric_threshold_number][2]: # type: ignore
            #direction = -1
            eps_max = eps  # Update the maximum bound
            eps = eps_max - (eps_max - eps_min) / 2.
        else:
            #direction = 1
            eps_min = eps  # Update the minimum bound
            eps = eps_min + (eps_max - eps_min) / 2.
                        
        if verbose:
            print(f"statistic = {metric} - next threshold = {metric_thresholds[metric_threshold_number][2]} at {metric_thresholds[metric_threshold_number][0]} CL")

        relative_error_eps = 2 * (eps_max - eps_min) / (eps_max + eps_min)
        relative_error_metric = 2 * np.abs(metric_thresholds[metric_threshold_number][2] - metric) / (metric_thresholds[metric_threshold_number][2] + metric)
        if verbose:
            print(f"relative_error_eps = {relative_error_eps}")
            print(f"relative_error_metric = {relative_error_metric}")
         
        # Check if the fn value is within the required accuracy of the threshold
        if relative_error_eps < x_tol and relative_error_metric < fn_tol:
            end = timer()
            if verbose:
                print(f"=======> statistic within required accuracy at {metric_thresholds[metric_threshold_number][0]} CL in {end - start} seconds")
            exclusion_list.append([metric_thresholds[metric_threshold_number][0], metric_name, eps, metric, end - start])
            metric_threshold_number += 1
            print("\n======================================================")
            print("New threshold. Resetting eps_min and eps_max.")
            start = timer() # Reset the timer
            iteration = 0
            eps_min, eps_max = eps, eps_max_start # Initialize the bounds
            
    end = timer()
    if verbose:
        print("Time elapsed:", end - start_global, "seconds.")
    result = {timestamp: {"test_config": test_kwargs,
                          "null_config": metric_config,
                          "deformation": deformation,
                          "parameters": {"ncomp": ncomp,
                                         "seed_dist": seed_dist,
                                         "x_tol": x_tol,
                                         "fn_tol": fn_tol,
                                         "eps_min": eps_min_start,
                                         "eps_max": eps_max_start,
                                         "max_iterations": max_iterations,
                                         "save": save,
                                         "verbose": verbose},
                          "exclusion_list": exclusion_list,
                          "eps_list": eps_list,
                          "metrics_list": metrics_list,
                          "time_elapsed": end - start_global}}
    
    # Saving if required
    if save:
        file_path = model_dir + "exclusion_limits.json"
        if verbose:
            print(f"Saving results in the file {file_path}")
        # Step 1: Read the existing content if the file exists
        existing_data = {}
        if os.path.exists(file_path):
            try:
                with open(file_path, "r") as file:
                    existing_data = json.load(file)
            except json.JSONDecodeError:
                # File is empty or corrupted, start with an empty dictionary
                existing_data = {}
        
        # Step 2: Update the dictionary with new results
        existing_data.update(result)
        
        # Step 3: Write the updated dictionary back to the file
        # Use this custom encoder when dumping your JSON data
        with open(file_path, "w") as file:
            json.dump(existing_data, file, cls=GMetrics.utils.CustomEncoder, indent=4) # type: ignore
    
    return result