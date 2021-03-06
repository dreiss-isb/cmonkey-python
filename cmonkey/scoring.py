# vi: sw=4 ts=4 et:
"""scoring.py - cMonkey scoring base classes

This file is part of cMonkey Python. Please see README and LICENSE for
more information and licensing details.
"""
LOG_FORMAT = '%(asctime)s %(levelname)-8s %(message)s'

import logging
import os
import os.path
import datamatrix as dm
from datetime import date
import util
import multiprocessing as mp
import membership as memb
import numpy as np
import cPickle
import gc
import sqlite3


# Official keys to access values in the configuration map
KEY_ORGANISM_CODE = 'organism_code'
KEY_NUM_ITERATIONS = 'num_iterations'
KEY_MATRIX_FILENAMES = 'matrix_filenames'
KEY_CACHE_DIR = 'cache_dir'
KEY_SEQUENCE_TYPES = 'sequence_types'
KEY_SEARCH_DISTANCES = 'search_distances'
KEY_SCAN_DISTANCES = 'scan_distances'
KEY_MULTIPROCESSING = 'multiprocessing'
KEY_OUTPUT_DIR = 'output_dir'
KEY_STRING_FILE = 'string_file'

USE_MULTIPROCESSING = True


def get_scaling(params, prefix):
    """returns a scaling function for the given prefix from the configuration parameters"""
    return util.get_iter_fun(params, prefix + 'scaling', params['num_iterations'])


class RunLog:
    """This is a class that captures information about a particular
    scoring function's behavior in a given iteration. In each iteration,
    a scoring function should log whether it was active and which scaling
    was applied.
    It simply appends log entries to a file to keep I/O and database load
    low.
    """
    def __init__(self, name, config_params):
        self.name = name
        self.output_file = '%s/%s.runlog' % (config_params['output_dir'], name)

    def log(self, iteration, was_active, scaling):
        with open(self.output_file, 'a') as logfile:
            logfile.write('%d:%d:%f\n' % (iteration, 1 if was_active else 0, scaling))


class ScoringFunctionBase:
    """Base class for scoring functions"""

    def __init__(self, organism, membership, ratios,
                 scaling_func,
                 schedule=lambda iteration: True,
                 config_params={}):
        """creates a function instance"""
        self.organism = organism
        self.membership = membership
        self.ratios = ratios
        self.scaling_func = scaling_func
        self.run_in_iteration = schedule

        # the cache_result parameter can be used by scoring functions
        # or users to fine-tune the behavior during non-compute operations
        # either recall a previous result from RAM or from a pickled
        # state. In general, setting this to True will be the best, but
        # if your environment has little memory, set this to False
        self.cache_result = True
        self.config_params = config_params
        if config_params is None:
            raise Exception('NO CONFIG PARAMS !!!')

    def name(self):
        """returns the name of this function
        Note to function implementers: make sure the name is
        unique for each used scoring function, since pickle paths
        are dependend on the name, non-unique function names will
        overwrite each other
        """
        raise Exception("please implement me")

    def pickle_path(self):
        """returns the function-specific pickle-path"""
        return '%s/%s_last.pkl' % (self.config_params['output_dir'], self.name())

    def last_cached(self):
        if self.cache_result:
            return self.cached_result
        elif os.path.exists(self.pickle_path()):
            with open(self.pickle_path()) as infile:
                return cPickle.load(infile)
        else:
            return None

    def compute(self, iteration_result, reference_matrix=None):
        """general compute method,
        iteration_result is a dictionary that contains the
        results generated by the scoring functions in the
        current computation.
        the reference_matrix is actually a hack that allows the scoring
        function to normalize its scores to the range of a reference
        score matrix. In the normal case, those would be the gene expression
        row scores"""
        iteration = iteration_result['iteration']

        if self.run_in_iteration(iteration):
            logging.info("running '%s' in iteration %d with scaling: %f",
                         self.name(), iteration, self.scaling(iteration))
            computed_result = self.do_compute(iteration_result,
                                              reference_matrix)
            # store the result for later, either by pickling them
            # or caching them
            if self.cache_result:
                self.cached_result = computed_result
            else:
                # pickle the result for future use
                logging.info("pickle result to %s", self.pickle_path())
                with open(self.pickle_path(), 'w') as outfile:
                    cPickle.dump(computed_result, outfile)

        elif self.cache_result:
            computed_result = self.cached_result
        elif os.path.exists(self.pickle_path()):
            with open(self.pickle_path()) as infile:
                computed_result = cPickle.load(infile)
        else:
            computed_result = None

        self.run_log.log(iteration,
                         self.run_in_iteration(iteration),
                         self.scaling(iteration_result['iteration']))
        return computed_result

    def compute_force(self, iteration_result, reference_matrix=None):
        """enforce computation, regardless of the iteration function"""
        iteration = iteration_result['iteration']
        computed_result = self.do_compute(iteration_result,
                                          reference_matrix)
        with open(self.pickle_path(), 'w') as outfile:
            cPickle.dump(computed_result, outfile)

        self.run_log.log(iteration,
                         self.run_in_iteration(iteration),
                         self.scaling(iteration_result['iteration']))
        return computed_result

    def do_compute(self, iteration_result, ref_matrix=None):
        raise Execption("implement me")

    def num_clusters(self):
        """returns the number of clusters"""
        return self.membership.num_clusters()

    def gene_names(self):
        """returns the gene names"""
        return self.ratios.row_names

    def rows_for_cluster(self, cluster):
        """returns the rows for the specified cluster"""
        return self.membership.rows_for_cluster(cluster)

    def scaling(self, iteration):
        """returns the quantile normalization scaling for the specified iteration"""
        if self.scaling_func is not None:
            return self.scaling_func(iteration)
        else:
            return 0.0

    def store_checkpoint_data(self, shelf):
        """Default implementation does not store checkpoint data"""
        pass

    def restore_checkpoint_data(self, shelf):
        """Default implementation does not store checkpoint data"""
        pass

    def run_logs(self):
        """returns a list of RunLog objects, giving information about
        the last run of this function"""
        return []


class ColumnScoringFunction(ScoringFunctionBase):
    """Scoring algorithm for microarray data based on conditions.
    Note that the score does not correspond to the normal scoring
    function output format and can therefore not be combined in
    a generic way (the format is |condition x cluster|)"""

    def __init__(self, organism, membership, ratios, schedule, config_params):
        """create scoring function instance"""
        ScoringFunctionBase.__init__(self, organism, membership,
                                     ratios, scaling_func=None,
                                     schedule=schedule,
                                     config_params=config_params)
        self.run_log = RunLog("column_scoring", config_params)

    def name(self):
        """returns the name of this scoring function"""
        return "Column"

    def do_compute(self, iteration_result, ref_matrix=None):
        """compute method, iteration is the 0-based iteration number"""
        return compute_column_scores(self.membership, self.ratios,
                                     self.num_clusters(),
                                     self.config_params[KEY_MULTIPROCESSING])


def compute_column_scores(membership, matrix, num_clusters,
                          use_multiprocessing=False):
    """Computes the column scores for the specified number of clusters"""

    def compute_substitution(cluster_column_scores):
        """calculate substitution value for missing column scores"""
        membership_values = []
        for cluster in xrange(1, num_clusters + 1):
            columns = membership.columns_for_cluster(cluster)
            column_scores = cluster_column_scores[cluster - 1]
            if column_scores is not None:
                colnames, scores = column_scores
                for col in xrange(len(colnames)):
                    if colnames[col] in columns:
                        membership_values.append(scores[col])
        return util.quantile(membership_values, 0.95)

    def make_submatrix(cluster):
        row_names = membership.rows_for_cluster(cluster)
        if len(row_names) > 1:
            return matrix.submatrix_by_name(row_names=row_names)
        else:
            return None

    if use_multiprocessing:
        pool = mp.Pool()
        cluster_column_scores = pool.map(compute_column_scores_submatrix,
                                         map(make_submatrix, xrange(1, num_clusters + 1)))
        pool.close()
        pool.join()
    else:
        cluster_column_scores = []
        for cluster in xrange(1, num_clusters + 1):
            cluster_column_scores.append(compute_column_scores_submatrix(
                make_submatrix(cluster)))

    substitution = compute_substitution(cluster_column_scores)

    # Convert scores into a matrix that have the clusters as columns
    # and conditions in the rows
    result = dm.DataMatrix(matrix.num_columns, num_clusters,
                           row_names=matrix.column_names)
    rvalues = result.values
    for cluster in xrange(num_clusters):
        column_scores = cluster_column_scores[cluster]

        if column_scores is not None:
            _, scores = column_scores
            scores[np.isnan(scores)] = substitution

        for row_index in xrange(matrix.num_columns):
            if column_scores is None:
                rvalues[row_index][cluster] = substitution
            else:
                _, scores = column_scores
                rvalues[row_index][cluster] = scores[row_index]
    result.fix_extreme_values()
    return result


def compute_column_scores_submatrix(matrix):
    """For a given matrix, compute the column scores.
    This is used to compute the column scores of the sub matrices that
    were determined by the pre-seeding, so typically, matrix is a
    submatrix of the input matrix that contains only the rows that
    belong to a certain cluster.
    The result is a DataMatrix with one row containing all the
    column scores

    This function normalizes diff^2 by the mean expression level, similar
    to "Index of Dispersion", see
    http://en.wikipedia.org/wiki/Index_of_dispersion
    for details
    """
    if matrix is None:
        return None
    colmeans = util.column_means(matrix.values)
    matrix_minus_colmeans_squared = np.square(matrix.values - colmeans)
    var_norm = np.abs(colmeans) + 0.01
    result = util.column_means(matrix_minus_colmeans_squared) / var_norm
    return (matrix.column_names, result)


def combine(result_matrices, score_scalings, membership, quantile_normalize):
    """This is  the combining function, taking n result matrices and scalings"""
    for m in result_matrices:
        m.fix_extreme_values()

    if quantile_normalize:
        if len(result_matrices) > 1:
            start_time = util.current_millis()
            result_matrices = dm.quantile_normalize_scores(result_matrices,
                                                           score_scalings)
            elapsed = util.current_millis() - start_time
            logging.info("quantile normalize in %f s.", elapsed / 1000.0)

        in_matrices = [m.values for m in result_matrices]

    else:
        in_matrices = []
        num_clusters = membership.num_clusters()
        mat = result_matrices[0]
        index_map = {name: index for index, name in enumerate(mat.row_names)}
        # we assume matrix 0 is always the gene expression score
        # we also assume that the matrices are already extreme value
        # fixed
        rsm = []
        for cluster in range(1, num_clusters + 1):
            row_members = sorted(membership.rows_for_cluster(cluster))
            rsm.extend([mat.values[index_map[row]][cluster - 1]
                        for row in row_members])
        scale = util.mad(rsm)
        if scale == 0:  # avoid that we are dividing by 0
            scale = util.r_stddev(rsm)
        if scale != 0:
            median_rsm = util.median(rsm)
            rsvalues = (mat.values - median_rsm) / scale
            num_rows, num_cols = rsvalues.shape
            rscores = dm.DataMatrix(num_rows, num_cols,
                                    mat.row_names,
                                    mat.column_names,
                                    values=rsvalues)
            rscores.fix_extreme_values()
        else:
            logging.warn("combiner scaling -> scale == 0 !!!")
            rscores = mat
        in_matrices.append(rscores.values)

        if len(result_matrices) > 1:
            rs_quant = util.quantile(rscores.values, 0.01)
            logging.info("RS_QUANT = %f", rs_quant)
            for i in range(1, len(result_matrices)):
                values = result_matrices[i].values
                qqq = abs(util.quantile(values, 0.01))
                #print "qqq(%d) = %f" % (i, qqq)
                if qqq == 0:
                    logging.error("very sparse score !!!")
                values = values / qqq * abs(rs_quant)
                in_matrices.append(values)

    if len(result_matrices) > 0:
        start_time = util.current_millis()
        # assuming same format of all matrices
        combined_score = np.zeros(in_matrices[0].shape)
        for i in xrange(len(in_matrices)):
            combined_score += in_matrices[i] * score_scalings[i]

        elapsed = util.current_millis() - start_time
        logging.info("combined score in %f s.", elapsed / 1000.0)
        matrix0 = result_matrices[0]  # as reference for names
        return dm.DataMatrix(matrix0.num_rows, matrix0.num_columns,
                             matrix0.row_names, matrix0.column_names,
                             values=combined_score)
    else:
        return None


class ScoringFunctionCombiner:
    """Taking advantage of the composite pattern, this combiner function
    exposes the basic interface of a scoring function in order to
    allow for nested scoring functions as they are used in the motif
    scoring
    """
    def __init__(self, organism, membership, scoring_functions,
                 scaling_func=None, schedule=None, config_params=None):
        """creates a combiner instance"""
        self.organism = organism  # not used, but constructor interface should be the same
        self.membership = membership
        self.scoring_functions = scoring_functions
        self.scaling_func = scaling_func
        self.config_params = config_params

    def compute_force(self, iteration_result, ref_matrix=None):
        """compute scores for one iteration, recursive force"""
        result_matrices = []
        score_scalings = []
        reference_matrix = ref_matrix
        iteration = iteration_result['iteration']
        for scoring_function in self.scoring_functions:
            # clean up before doing something complicated
            gc.collect()

            if reference_matrix is None and len(result_matrices) > 0:
                reference_matrix = result_matrices[0]

            matrix = scoring_function.compute_force(iteration_result, reference_matrix)
            if matrix is not None:
                result_matrices.append(matrix)
                score_scalings.append(scoring_function.scaling(iteration))

                if self.config_params['log_subresults']:
                    self.log_subresult(scoring_function, matrix)
        return combine(result_matrices, score_scalings, self.membership,
                       self.config_params['quantile_normalize'])

    def compute(self, iteration_result, ref_matrix=None):
        """compute scores for one iteration"""
        result_matrices = []
        score_scalings = []
        reference_matrix = ref_matrix
        iteration = iteration_result['iteration']
        for scoring_function in self.scoring_functions:
            # clean up before doing something complicated
            gc.collect()

            # This  is actually a hack in order to propagate
            # a reference matrix to the compute function
            # This could have negative impact on scalability
            if reference_matrix is None and len(result_matrices) > 0:
                reference_matrix = result_matrices[0]

            matrix = scoring_function.compute(iteration_result, reference_matrix)
            if matrix is not None:
                result_matrices.append(matrix)
                score_scalings.append(scoring_function.scaling(iteration))

                if self.config_params['log_subresults']:
                    self.log_subresult(scoring_function, matrix)

        return combine(result_matrices, score_scalings, self.membership,
                       self.config_params['quantile_normalize'])

    def combine_cached(self, iteration):
        """Combine the cached results of the contained scoring function.
        This is used by the post adjustment"""
        result_matrices = []
        score_scalings = []
        for scoring_function in self.scoring_functions:
            matrix = scoring_function.last_cached()
            if matrix is not None:
                result_matrices.append(matrix)
                score_scalings.append(scoring_function.scaling(iteration))

        return combine(result_matrices, score_scalings, self.membership, True)


    def log_subresult(self, score_function, matrix):
        """output an accumulated subresult to the log"""
        scores = []
        mvalues = matrix.values
        for cluster in xrange(1, matrix.num_columns + 1):
            cluster_rows = self.membership.rows_for_cluster(cluster)
            for row in xrange(matrix.num_rows):
                if matrix.row_names[row] in cluster_rows:
                    scores.append(mvalues[row][cluster - 1])
        logging.info("function '%s', trim mean score: %f",
                     score_function.name(),
                     util.trim_mean(scores, 0.05))

    def scaling(self, iteration):
        """returns the scaling for the specified iteration"""
        return self.scaling_func(iteration)

    def store_checkpoint_data(self, shelf):
        """recursively invokes store_checkpoint_data() on the children"""
        for scoring_func in self.scoring_functions:
            scoring_func.store_checkpoint_data(shelf)

    def restore_checkpoint_data(self, shelf):
        """recursively invokes store_checkpoint_data() on the children"""
        for scoring_func in self.scoring_functions:
            scoring_func.restore_checkpoint_data(shelf)

    def run_logs(self):
        """joins all contained function's run logs"""
        result = []
        for scoring_func in self.scoring_functions:
            result.extend(scoring_func.run_logs())
        return result
