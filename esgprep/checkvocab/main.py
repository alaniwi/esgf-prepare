#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
    :platform: Unix
    :synopsis: Checks DRS vocabulary against configuration files.

"""

import logging
import os
import re
import sys

from esgprep.utils import parser, utils
from esgprep.utils.constants import *
from esgprep.utils.exceptions import *


class ProcessingContext(object):
    """
    Encapsulates the following processing context/information for main process:

    +------------------------+-------------+--------------------------------------------+
    | Attribute              | Type        | Description                                |
    +========================+=============+============================================+
    | *self*.directory       | *list*      | Paths to scan                              |
    +------------------------+-------------+--------------------------------------------+
    | *self*.dataset_list    | *str*       | Path of file containing dataset IDs        |
    +------------------------+-------------+--------------------------------------------+
    | *self*.project         | *str*       | Project                                    |
    +------------------------+-------------+--------------------------------------------+
    | *self*.cfg             | *callable*  | Configuration file parser                  |
    +------------------------+-------------+--------------------------------------------+
    | *self*.project_section | *str*       | Project section name in configuration file |
    +------------------------+-------------+--------------------------------------------+
    | *self*.filter          | *re object* | File filter as regex pattern               |
    +------------------------+-------------+--------------------------------------------+
    | *self*.pattern         | *re object* | DRS regex pattern without version          |
    +------------------------+-------------+--------------------------------------------+
    | *self*.facets_from_directory_format  | Set of the DRS facets obtained from the    |
    |                        | *set*       | directory_format                           |
    +------------------------+-------------+--------------------------------------------+
    | *self*.facets_of_type_enum           | Set of the DRS facets that have type enum  |
    |                        | *set*       | in the categories table                    |
    +------------------------+-------------+--------------------------------------------+
    | *self*.dataset_id_pattern            | DRS regex pattern from dataset_id          |
    |                        | *re object* | config variable                            |
    +------------------------+-------------+--------------------------------------------+
    | *self*.facets_from_dataset_id        | Set of the DRS facets obtained from the    |
    |                        | *set*       | dataset_id                                 |
    +------------------------+-------------+--------------------------------------------+

    :param ArgumentParser args: Parsed command-line arguments
    :returns: The processing context
    :rtype: *ProcessingContext*

    """

    def __init__(self, args):

        self.directory = args.directory
        self.dataset_list = args.dataset_list
        self.project = args.project
        self.verbosity = args.v
        self.filter = args.filter
        self.project_section = 'project:{0}'.format(args.project)

        self.cfg = parser.CfgParser(args.i, section=self.project_section)

        self.pattern, self.facets_from_directory_format = \
            self.cfg.get_pattern_and_facets_from_directory_format(self.project_section)

        self.facets_of_type_enum = self.cfg.get_facets_of_type_enum(self.project_section)

        self.dataset_id_pattern, self.facets_from_dataset_id = \
            self.cfg.get_pattern_and_facets_from_dataset_format(self.project_section)


def yield_datasets_from_file(ctx):
    """
    Yields datasets to process from a text file.  Each line may contain the dataset with optional 
    appended .v<version> or #<version>, and only the part without the version is returned.
    """
    trailing = re.compile("((\.v|#)[0-9]+)?\s*$")  # re for optional version and any whitespace
    with open(ctx.dataset_list) as f:
        for line in f:
            yield trailing.sub("", line)

def yield_files_from_tree(ctx):
    """
    Yields datasets to process. Only the "dataset part" of the DRS tree is returned
    (i.e., from "root" to the facet before the "version" facet).

    :param esgprep.checkvocab.main.ProcessingContext ctx: The processing context
    :returns: The dataset as a part of the DRS tree
    :rtype: *iter*

    """
    for directory in ctx.directory:
        for root, _, filenames in utils.walk(directory, downstream=True, followlinks=True):
            if '/files/' not in root:
                for filename in filenames:
                    ffp = os.path.join(root, filename)
                    if os.path.isfile(ffp) and re.match(ctx.filter, filename) is not None:
                        yield ffp


def get_facet_values_from_tree(ctx, dsets, facets):
    """
    Returns all used values of each facet from the DRS tree, according to the supplied directories.

    :param esgprep.checkvocab.main.ProcessingContext ctx: The processing context
    :param iter dsets: The dataset part of the DRS tree
    :param list facets: The facets list
    :returns: The declared values of each facet
    :rtype: *dict*

    """
    logging.info('Harvesting facets values from DRS tree...')
    used_values = dict((facet, set()) for facet in facets)
    for dset in dsets:
        try:
            attributes = re.match(ctx.pattern, dset).groupdict()
        except:
            raise DirectoryNotMatch(os.path.realpath(dset), ctx.pattern, ctx.project_section, ctx.cfg.read_paths)
        # Each facet is ensured to be included into "attributes" from matching
        for facet in facets:
            used_values[facet].add(attributes[facet])
    return used_values

def get_facet_values_from_dataset_list(ctx, dsets, facets):
    """
    Returns all used values of each facet from the supplied of dataset IDs.

    :param esgprep.checkvocab.main.ProcessingContext ctx: The processing context
    :param iter dsets: The dataset part of the DRS tree
    :param list facets: The facets list
    :returns: The declared values of each facet
    :rtype: *dict*

    """
    logging.info('Harvesting facets values from dataset list...')
    used_values = dict((facet, set()) for facet in facets)
    
    for dset in dsets:
        try:
            attributes = re.match(ctx.dataset_id_pattern, dset).groupdict()
        except:
            raise DatasetNotMatch(dset, ctx.dataset_id_pattern, ctx.project_section)
        # Each facet is ensured to be included into "attributes" from matching
        for facet in facets:
            used_values[facet].add(attributes[facet])
    return used_values


def get_facet_values_from_config(cfg, section, facets):
    """
    Returns all declared values of each facet from the configuration file, according to the project section.

    :param CfgParser cfg: The configuration file parser
    :param str section: The section name to parse
    :param set facets: The set of facets to check
    :returns: The declared values of each facet
    :rtype: *dict*

    """
    declared_values = {}
    for facet in facets:
        logging.info('Collecting values from INI file(s) for "{0}" facet...'.format(facet))
        try:
            declared_values[facet], _ = cfg.get_options(section, facet)
            if not isinstance(declared_values[facet], type(re.compile("", 0))):
                declared_values[facet] = set(declared_values[facet])
        except NoConfigOptions:
            for option in cfg.get_options_from_list(section, 'maps'):
                maptable = cfg.get(section, option)
                from_keys, _ = parser.split_map_header(maptable.split('\n')[0])
                if facet in from_keys:
                    declared_values[facet] = set(cfg.get_options_from_map(section, option, facet))
        finally:
            if facet not in declared_values.keys():
                raise NoConfigOptions(facet, section, cfg.read_paths)
    return declared_values


def compare_values(facets, used_values, declared_values, verbosity=False):
    """
    Compares used values from DRS tree with all declared values in configuration file for each facet.

    :param list facets: The facets list
    :param dict used_values: Dictionary of sets of used values from DRS tree
    :param dict declared_values: Dictionary of sets of  declared values from the configuration file
    :param boolean verbosity: Display declared/undeclared and used/unused values if True
    :returns: True if undeclared values in configuration file are used in DRS tree
    :rtype: *boolean*

    """
    any_undeclared = False
    for facet in facets:
        if isinstance(declared_values[facet], type(re.compile("", 0))):
            declared_values[facet] = set([v for v in used_values[facet] if declared_values[facet].search(v)])
        if verbosity:
            if not declared_values[facet]:
                logging.warning('{0} facet - No declared values'.format(facet))
                values = ', '.join(sorted(used_values[facet]))
                logging.info('{0} facet - Used values: {1}'.format(facet, values))
            else:
                values = ', '.join(sorted(declared_values[facet]))
                logging.info('{0} facet - Declared values: {1}'.format(facet, values))
                values = ', '.join(sorted(used_values[facet]))
                logging.info('{0} facet - Used values: {1}'.format(facet, values))
        undeclared_values = used_values[facet].difference(declared_values[facet])
        unused_values = declared_values[facet].difference(used_values[facet])
        updated_values = used_values[facet].union(declared_values[facet])
        if undeclared_values:
            values = ', '.join(sorted(undeclared_values))
            logging.info('{0} facet - UNDECLARED values: {1}'.format(facet, values))
            any_undeclared = True
            values = ', '.join(sorted(updated_values))
            logging.info('{0} facet - UPDATED values to declare: {1}'.format(facet, values))
        if unused_values and verbosity:
            values = ', '.join(sorted(unused_values))
            logging.info('{0} facet - Unused values: {1}'.format(facet, values))
    if any_undeclared:
        logging.error('Result: THERE WERE UNDECLARED VALUES USED.')
    else:
        logging.info('Result: ALL USED VALUES ARE PROPERLY DECLARED.')
    return any_undeclared


def main(args):
    """
    Main process that:

     * Instantiates processing context
     * Parses the configuration files options and values,
     * Deduces facets and values from directories,
     * Compares the values of each facet between both,
     * Print or log the checking.

    :param ArgumentParser args: Parsed command-line arguments

    """
    # Instantiate processing context from command-line arguments or SYNDA job dictionary
    ctx = ProcessingContext(args)
    # Get set of facets to process: only those that are both in the directory_format 
    # and of type enum
    if ctx.directory:
        facets = (set(ctx.facets_from_directory_format) & set(ctx.facets_of_type_enum)) - set(IGNORED_KEYS)
        # Walk trough DRS to get all dataset roots
        dsets = yield_files_from_tree(ctx)
        # Get facets values used by DRS tree
        facet_values_found = get_facet_values_from_tree(ctx, dsets, list(facets))
    else:
        facets = (set(ctx.facets_from_dataset_id) & set(ctx.facets_of_type_enum)) - set(IGNORED_KEYS)
        dsets = yield_datasets_from_file(ctx)
        facet_values_found = get_facet_values_from_dataset_list(ctx, dsets, list(facets))
    # Get facets values declared in configuration file
    facet_values_config = get_facet_values_from_config(ctx.cfg, ctx.project_section, facets)
    # Compare values from tree against values from configuration file
    any_disallowed = compare_values(list(facets), facet_values_found, facet_values_config, ctx.verbosity)
    if any_disallowed:
        sys.exit(1)
