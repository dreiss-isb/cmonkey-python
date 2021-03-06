#!/usr/bin/python
# vi: sw=4 ts=4 et:
"""cmonkey.py - cMonkey top-level module

This file is part of cMonkey Python. Please see README and LICENSE for
more information and licensing details.
"""
import os.path
import cmonkey.cmonkey_run as cmr
import cmonkey.datamatrix as dm
import cmonkey.util as util
import argparse
import logging
from cmonkey.schedule import make_schedule
import ConfigParser
import tempfile
import cmonkey.scoring as scoring
import random



def set_config(cmonkey_run, config):
    def set_scaling(section, prefix):
        try:
            cmonkey_run[prefix + 'scaling_const'] = config.getfloat(section, 'scaling_const')
            return
        except:
            pass
        try:
            cmonkey_run[prefix + 'scaling_rvec'] = config.get(section, 'scaling_rvec')
        except:
            raise Exception("no scaling found for section '%s'" % section)

    # override directories
    tmp_dir = config.get('General', 'tmp_dir')
    if tmp_dir:
        tempfile.tempdir = tmp_dir
    cmonkey_run['output_dir'] = config.get('General', 'output_dir')
    cmonkey_run['cache_dir'] = config.get('General', 'cache_dir')

    cmonkey_run['num_iterations'] = config.getint("General", "num_iterations")
    cmonkey_run['start_iteration'] = config.getint("General", "start_iteration")
    cmonkey_run['out_database'] = os.path.join(cmonkey_run['output_dir'],
                                               config.get("General", "dbfile_name"))
    cmonkey_run['multiprocessing'] = config.getboolean('General', 'use_multiprocessing')
    cmonkey_run['postadjust'] = config.getboolean('General', 'postadjust')
    cmonkey_run['log_subresults'] = config.getboolean('General', 'log_subresults')
    cmonkey_run['add_fuzz'] = config.get('General', 'add_fuzz')
    cmonkey_run['checkpoint_interval'] = config.getint('General', 'checkpoint_interval')
    try:
        cmonkey_run['random_seed'] = config.getint('General', 'random_seed')
    except:
        cmonkey_run['random_seed'] = None

    # Quantile normalization is false by default in cMonkey-R
    cmonkey_run['quantile_normalize'] = config.getboolean('Scoring', 'quantile_normalize')
    # membership default parameters
    cmonkey_run['memb.min_cluster_rows_allowed'] = config.getint('Membership', 'min_cluster_rows_allowed')
    cmonkey_run['memb.max_cluster_rows_allowed'] = config.getint('Membership', 'max_cluster_rows_allowed')
    cmonkey_run['memb.prob_row_change'] = config.getfloat('Membership', 'probability_row_change')
    cmonkey_run['memb.prob_col_change'] = config.getfloat('Membership', 'probability_column_change')
    cmonkey_run['memb.max_changes_per_row'] = config.getint('Membership', 'max_changes_per_row')
    cmonkey_run['memb.max_changes_per_col'] = config.getint('Membership', 'max_changes_per_column')

    cmonkey_run['sequence_types'] = config.get('Motifs', 'sequence_types').split(',')
    cmonkey_run['search_distances'] = {}
    cmonkey_run['scan_distances'] = {}
    for seqtype in cmonkey_run['sequence_types']:
        cat = "SequenceType-%s" % seqtype
        cmonkey_run['search_distances'][seqtype] = tuple(
            map(int, config.get(cat, 'search_distance').split(',')))
        cmonkey_run['scan_distances'][seqtype] = tuple(
            map(int, config.get(cat, 'scan_distance').split(',')))

    cmonkey_run['row_schedule'] = make_schedule(config.get("Rows", "schedule"))
    cmonkey_run['column_schedule'] = make_schedule(config.get("Columns", "schedule"))
    cmonkey_run['meme_schedule'] = make_schedule(config.get("MEME", "schedule"))
    cmonkey_run['motif_schedule'] = make_schedule(config.get("Motifs", "schedule"))
    cmonkey_run['network_schedule'] = make_schedule(config.get("Networks", "schedule"))

    cmonkey_run['stats_freq'] = config.getint('General', 'stats_frequency')
    cmonkey_run['result_freq'] = config.getint('General', 'result_frequency')

    # parse the scalings
    set_scaling('Motifs', 'motif_')
    set_scaling('Rows', 'row_')
    set_scaling('Networks', 'network_')

    try:
        cmonkey_run['nmotifs_rvec'] = config.get('MEME', 'nmotifs_rvec')
    except:
        raise Exception("no setting found to retrieve the MEME nmotifs function")


# if we were installed through Debian package management, default.ini is found here
SYSTEM_INI_PATH = '/etc/cmonkey-python/default.ini'
USER_INI_PATH = 'config/default.ini'

if __name__ == '__main__':
    description = """cMonkey (Python port) (c) 2011-2012,
Institute for Systems Biology
This program is licensed under the General Public License V3.
See README and LICENSE for details.\n"""

    # read default configuration parameters
    config = ConfigParser.ConfigParser()
    if os.path.exists(USER_INI_PATH):
        config.read(USER_INI_PATH)
    elif os.path.exists(SYSTEM_INI_PATH):
        config.read(SYSTEM_INI_PATH)
    else:
        raise Exception('could not find default.ini !')

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('--ratios', required=True,
                        help='tab-separated ratios matrix file')

    parser.add_argument('--organism', help='KEGG organism code', default=None)
    parser.add_argument('--out', default=config.get("General", "output_dir"),
                        help='output directory')
    parser.add_argument('--cachedir', default=config.get("General", "cache_dir"),
                        help="path to cache directory")
    parser.add_argument('--string', help='tab-separated STRING file for the organism',
                        default=None)
    parser.add_argument('--operons', help='tab-separated STRING file for the organism',
                        default=None)
    parser.add_argument('--checkpoint', help='checkpoint-file')
    parser.add_argument('--checkratios', action="store_true",
                        help='check gene expression quality')
    parser.add_argument('--remap_network_nodes', action="store_true",
                        help='network nodes are not named to RSAT primary names')
    parser.add_argument('--logfile', default=None, help="""path to log file""")
    parser.add_argument('--keep_memeout', action="store_true",
                        help="""keep MEME output files""")
    parser.add_argument('--ncbi_code', default=None, help="NCBI taxonomy id")
    parser.add_argument('--numclusters', type=int,
                        default=None, help="override the number of clusters")

    parser.add_argument('--nomotifs', action="store_true", help="deactivate motif scoring")
    parser.add_argument('--nonetworks', action="store_true", help="deactivate network scoring")
    parser.add_argument('--nostring', action="store_true", help="deactivate STRING network scoring")
    parser.add_argument('--nooperons', action="store_true", help="deactivate operon network scoring")
    parser.add_argument('--config', default=None, help="additional configuration file")
    parser.add_argument('--debug', action="store_true",
                        help="""run in debug mode""")
    parser.add_argument('--random_seed', type=int)

    # RSAT overrides
    parser.add_argument('--rsat_dir', default=None,
                        help="""RSAT override: data directory""")
    parser.add_argument('--rsat_organism', default=None,
                        help="""override the RSAT organism name""")

    args = parser.parse_args()

    # no organism provided -> dummy organism
    if args.organism is None:
        print("WARNING - no organism provided - assuming that you want to score ratios only or don't use automatic download")
        if not args.rsat_dir:
            args.nomotifs = True
        if not args.string and not args.operons:
            args.nonetworks = True

    # user overrides in config files
    if args.config:
        config.read(args.config)

    matrix_factory = dm.DataMatrixFactory([dm.nochange_filter,
                                           dm.center_scale_filter])
    matrix_filename = args.ratios

    if matrix_filename.startswith('http://'):
        indata = util.read_url(matrix_filename)
        infile = util.dfile_from_text(indata, has_header=True, quote='\"')
    else:
        infile = util.read_dfile(matrix_filename, has_header=True, quote='\"')

    matrix = matrix_factory.create_from(infile)
    infile = None

    # override number of clusters either on the command line or through
    # the config file
    try:
        num_clusters = config.getint("General", "num_clusters")
    except:
        num_clusters = args.numclusters

    cmonkey_run = cmr.CMonkeyRun(args.organism, matrix,
                                 string_file=args.string,
                                 rsat_organism=args.rsat_organism,
                                 log_filename=args.logfile,
                                 remap_network_nodes=args.remap_network_nodes,
                                 ncbi_code=args.ncbi_code,
                                 num_clusters=num_clusters,
                                 operon_file=args.operons,
                                 rsat_dir=args.rsat_dir)
    set_config(cmonkey_run, config)

    cmonkey_run['output_dir'] = args.out
    cmonkey_run['cache_dir'] = args.cachedir
    cmonkey_run['debug'] = args.debug
    cmonkey_run['keep_memeout'] = args.keep_memeout or args.debug
    cmonkey_run['donetworks'] = not args.nonetworks
    cmonkey_run['domotifs'] = not args.nomotifs and cmonkey_run['meme_version']
    cmonkey_run['use_string'] = not args.nostring
    cmonkey_run['use_operons'] = not args.nooperons
    if args.random_seed:
        cmonkey_run['random_seed'] = args.random_seed

    if cmonkey_run['random_seed']:
        random.seed(cmonkey_run['random_seed'])
        util.r_set_seed(cmonkey_run['random_seed'])

    proceed = True
    checkratios = args.checkratios

    if args.checkratios:
        thesaurus = cmonkey_run.organism().thesaurus()
        logging.info("Checking the quality of the input matrix names...")
        found = [name for name in matrix.row_names if name in thesaurus]
        num_found = len(found)
        total = len(matrix.row_names)
        percent = (float(num_found) / float(total)) * 100.0
        proceed = percent > 50.0

    # Set update frequency to every iteration, so the full results are written
    if cmonkey_run['debug']:
        cmonkey_run['stats_freq'] = 1
        cmonkey_run['result_freq'] = 1


    if not proceed:
        logging.error("# genes found: %d, # total: %d, %f %% - please check your ratios file",
                      num_found, total, percent)
    else:
        if args.checkpoint:
            cmonkey_run.run_from_checkpoint(args.checkpoint)
        else:
            cmonkey_run.run()
