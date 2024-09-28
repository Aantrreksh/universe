#!/usr/bin/env python

############################################################################
#
# MODULE:    v.vect.stats.multi
# AUTHOR(S): Vaclav Petras
# PURPOSE:   Compute statistics for multiple columns using v.vect.stats
# COPYRIGHT: (C) 2020 by Vaclav Petras and the GRASS Development Team
#
#                This program is free software under the GNU General Public
#                License (>=v2). Read the file COPYING that comes with GRASS
#                for details.
#
#############################################################################

"""Compute zonal statistics for each column."""

# %module
# % description: Computes isochrones from collection point in a sewershed
# % keyword: vector
# % keyword: attribute table
# % keyword: statistics
# % keyword: univariate statistics
# % keyword: zonal statistics
# % keyword: columns
# %end
# %option G_OPT_V_INPUT
# % key: points
# % label: Name of existing vector map with points
# % description: Vector map with one or more attributes
# %end
# %option G_OPT_V_INPUT
# % key: areas
# % label: Name of existing vector map with points
# % description: Vector map with one or more attributes
# %end
# %option G_OPT_V_TYPE
# % key: type
# % required: no
# % multiple: yes
# % options: point,centroid
# % answer: point
# % guisection: Selection
# %end
# %option G_OPT_V_FIELD
# % key: points_layer
# % label: Layer number for points map
# % guisection: Selection
# % guidependency: points_where,points_column
# %end
# %option G_OPT_V_CATS
# % key: points_cats
# % label: Category values for points map
# % guisection: Selection
# %end
# %option G_OPT_DB_WHERE
# % key: points_where
# % label: WHERE conditions of SQL statement without 'where' keyword for points map
# % guisection: Selection
# %end
# %option G_OPT_V_FIELD
# % key: areas_layer
# % label: Layer number for area map
# % guisection: Selection
# % guidependency: areas_where,count_column,stats_column
# %end
# %option G_OPT_V_CATS
# % key: areas_cats
# % label: Category values for area map
# % guisection: Selection
# %end
# %option G_OPT_DB_WHERE
# % key: areas_where
# % label: WHERE conditions of SQL statement without 'where' keyword for area map
# % guisection: Selection
# %end
# %option
# % key: method
# % type: string
# % required: yes
# % multiple: yes
# % options: sum,average,median,mode,minimum,maximum,range,stddev,variance,diversity
# % description: Method for aggregate statistics
# %end
# %option G_OPT_DB_COLUMN
# % key: points_columns
# % multiple: yes
# % label: Column names of points map to compute statistics from
# % description: Defaults to all numeric columns. The specified columns must be numeric
# %end
# %option G_OPT_DB_COLUMN
# % key: count_column
# % required: yes
# % label: Column name to upload points count
# % description: Column to hold points count, must be of type integer, will be created if not existing
# %end
# %option G_OPT_DB_COLUMN
# % key: stats_columns
# % label: Column names to upload statistics (generated by default)
# % description: By default, generated as source column name underscore method name
# %end


import sys
from itertools import product

import grass.script as gs

try:
    from grass.script import sql_type_is_numeric
except ImportError:
    _SQL_INT_TYPES = [
        "INT",
        "INTEGER",
        "TINYINT",
        "SMALLINT",
        "MEDIUMINT",
        "BIGINT",
        "UNSIGNED BIG INT",
        "INT2",
        "INT8",
    ]

    _SQL_FLOAT_TYPES = [
        "REAL",
        "DOUBLE",
        "DOUBLE PRECISION",
        "FLOAT",
        "FLOATING POINT",
    ]

    _SQL_NUMERIC_TYPES = _SQL_INT_TYPES + _SQL_FLOAT_TYPES

    def sql_type_is_numeric(sql_type):
        """Return True if SQL type is numeric
        Returns True for known integral and floating point types, False otherwise.
        """
        return sql_type.upper() in _SQL_NUMERIC_TYPES


def main():
    options, flags = gs.parser()

    points_name = options["points"]
    points_layer = options["points_layer"]
    points_columns = []
    if options["points_columns"]:
        points_columns = options["points_columns"].split(",")

    # TODO: Add check points exist before we query the metadata.

    input_vector_columns = gs.vector_columns(points_name, points_layer)

    if not points_columns:
        # Get all numeric columns from the table.
        # Get only the names ordered in the same as in the database.
        all_column_names = gs.vector_columns(points_name, points_layer, getDict=False)
        for name in all_column_names:
            # TODO: Find out what is the key column (usually cat) and skip it.
            column_type = input_vector_columns[name]["type"]
            if sql_type_is_numeric(column_type):
                points_columns.append(name)
    else:
        # Check the user provided columns.
        for name in points_columns:
            try:
                column_info = input_vector_columns[name]
            except KeyError:
                gs.fatal(
                    _(
                        "Column <{name}> not found in vector map <{points_name}>,"
                        " layer <{points_layer}>"
                    ).format(**locals())
                )
            column_type = column_info["type"]
            if not sql_type_is_numeric(column_type):
                gs.fatal(
                    _(
                        "Column <{name}> in <{points_name}> is {column_type}"
                        " which is not a numeric type"
                    ).format(**locals())
                )

    methods = options["method"].split(",")
    stats_columns_names = []
    num_new_columns = len(points_columns) * len(methods)
    if options["stats_columns"]:
        stats_columns_names = options["stats_columns"].split(",")
        names_provided = len(stats_columns_names)
        if names_provided != num_new_columns:
            gs.fatal(
                _(
                    "Number of provided stats_columns ({names_provided})"
                    " does not correspond to number of names needed"
                    " for every combination of points_columns and methods"
                    " ({num_points_columns} * {num_methods} = {names_needed})"
                ).format(
                    names_provided=names_provided,
                    num_points_columns=len(points_columns),
                    num_methods=len(methods),
                    names_needed=num_new_columns,
                )
            )
        num_unique_names = len(set(stats_columns_names))
        if names_provided != num_unique_names:
            gs.fatal(
                _(
                    "Names in stats_columns are not unique"
                    " ({names_provided} items provied"
                    " but only {num_unique_names} are unique)"
                ).format(
                    names_provided=names_provided,
                    num_unique_names=num_unique_names,
                )
            )

    modified_options = options.copy()
    # Remove options we are handling here.
    del modified_options["points_columns"]
    del modified_options["stats_columns"]
    del modified_options["method"]

    # Note that the count_column is mandatory for v.vect.stats,
    # so it is simply computed more than once. Ideally, it would
    # be optional for this module which would probably mean better handling of
    # number of point and n in statistions in v.vect.stats (unless we simply
    # use temporary name and drop the column at the end).

    # The product function advances the rightmost element on every iteration,
    # so first we get all methods for one column. This is important to
    # the user if stats_columns is provided.
    for i, (points_column, method) in enumerate(product(points_columns, methods)):
        if stats_columns_names:
            stats_column_name = stats_columns_names[i]
        else:
            stats_column_name = f"{points_column}_{method}"
        gs.run_command(
            "v.vect.stats",
            method=method,
            points_column=points_column,
            stats_column=stats_column_name,
            quiet=True,
            **modified_options,
            errors="exit",
        )
        gs.percent(i, num_new_columns, 1)
    gs.percent(1, 1, 1)

    return 0


if __name__ == "__main__":
    sys.exit(main())
