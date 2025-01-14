# ----------------------------------------------------------------------
#   LAMMPS - Large-scale Atomic/Molecular Massively Parallel Simulator
#   https://www.lammps.org/ Sandia National Laboratories
#   Steve Plimpton, sjplimp@sandia.gov
#
#   Copyright (2003) Sandia Corporation.  Under the terms of Contract
#   DE-AC04-94AL85000 with Sandia Corporation, the U.S. Government retains
#   certain rights in this software.  This software is distributed under
#   the GNU General Public License.
#
#   See the README file in the top-level LAMMPS directory.
# -------------------------------------------------------------------------

################################################################################
# LAMMPS output formats
# Written by Richard Berger <richard.berger@temple.edu>
# and Axel Kohlmeyer <akohlmey@gmail.com>
################################################################################

import re, yaml
try:
  from yaml import CSafeLoader as Loader, CSafeDumper as Dumper
except ImportError:
  from yaml import SafeLoader as Loader, SafeDumper as Dumper

class LogFile:
  """Reads LAMMPS log files and extracts the thermo information

  It supports the line, multi, and yaml thermo output styles.

  :param filename: path to log file
  :type  filename: str

  :ivar runs: List of LAMMPS runs in log file. Each run is a dictionary with
              thermo fields as keys, storing the values over time
  :ivar errors: List of error lines in log file
  """

  STYLE_DEFAULT = 0
  STYLE_MULTI   = 1
  STYLE_YAML    = 2

  def __init__(self, filename):
    alpha = re.compile(r'[a-df-zA-DF-Z]') # except e or E for floating-point numbers
    kvpairs = re.compile(r'([a-zA-Z_0-9]+)\s+=\s*([0-9\.eE\-]+)')
    style = LogFile.STYLE_DEFAULT
    yamllog = ""
    self.runs = []
    self.errors = []
    with open(filename, 'rt') as f:
        in_thermo = False
        in_data_section = False
        for line in f:
            if "ERROR" in line or "exited on signal" in line:
                self.errors.append(line)

            elif re.match(r'^ *Step ', line):
                in_thermo = True
                in_data_section = True
                keys = line.split()
                current_run = {}
                for k in keys:
                    current_run[k] = []

            elif re.match(r'^(keywords:.*$|data:$|---$|  - \[.*\]$)', line):
                style = LogFile.STYLE_YAML
                yamllog += line;
                current_run = {}

            elif re.match(r'^\.\.\.$', line):
                thermo = yaml.load(yamllog, Loader=Loader)
                for k in thermo['keywords']:
                    current_run[k] = []
                for step in thermo['data']:
                    icol = 0
                    for k in thermo['keywords']:
                        current_run[k].append(step[icol])
                        icol += 1
                self.runs.append(current_run)
                yamllog = ""

            elif re.match(r'^------* Step ', line):
                if not in_thermo:
                   current_run = {'Step': [], 'CPU': []}
                in_thermo = True
                in_data_section = True
                style = LogFile.STYLE_MULTI
                str_step, str_cpu = line.strip('-\n').split('-----')
                step = float(str_step.split()[1])
                cpu  = float(str_cpu.split('=')[1].split()[0])
                current_run["Step"].append(step)
                current_run["CPU"].append(cpu)

            elif line.startswith('Loop time of'):
                in_thermo = False
                if style != LogFile.STYLE_YAML:
                    self.runs.append(current_run)

            elif in_thermo and in_data_section:
                if style == LogFile.STYLE_DEFAULT:
                    if alpha.search(line):
                        continue
                    for k, v in zip(keys, map(float, line.split())):
                        current_run[k].append(v)

                elif style == LogFile.STYLE_MULTI:
                    if '=' not in line:
                        in_data_section = False
                        continue
                    for k,v in kvpairs.findall(line):
                        if k not in current_run:
                            current_run[k] = [float(v)]
                        else:
                            current_run[k].append(float(v))

class AvgChunkFile:
  """Reads files generated by fix ave/chunk

  :param filename: path to ave/chunk file
  :type  filename: str

  :ivar timesteps: List of timesteps stored in file
  :ivar total_count: total count over time
  :ivar chunks: List of chunks. Each chunk is a dictionary containing its ID, the coordinates, and the averaged quantities
  """
  def __init__(self, filename):
    with open(filename, 'rt') as f:
      timestep = None
      chunks_read = 0

      self.timesteps = []
      self.total_count = []
      self.chunks = []

      for lineno, line in enumerate(f):
        if lineno == 0:
          if not line.startswith("# Chunk-averaged data for fix"):
            raise Exception("Chunk data reader only supports default avg/chunk headers!")
          parts = line.split()
          self.fix_name = parts[5]
          self.group_name = parts[8]
          continue
        elif lineno == 1:
          if not line.startswith("# Timestep Number-of-chunks Total-count"):
            raise Exception("Chunk data reader only supports default avg/chunk headers!")
          continue
        elif lineno == 2:
          if not line.startswith("#"):
            raise Exception("Chunk data reader only supports default avg/chunk headers!")
          columns = line.split()[1:]
          ndim = line.count("Coord")
          compress = 'OrigID' in line
          if ndim > 0:
            coord_start = columns.index("Coord1")
            coord_end   = columns.index("Coord%d" % ndim)
            ncount_start = coord_end + 1
            data_start = ncount_start + 1
          else:
            coord_start = None
            coord_end = None
            ncount_start = 2
            data_start = 3
          continue

        parts = line.split()

        if timestep is None:
          timestep = int(parts[0])
          num_chunks = int(parts[1])
          total_count = float(parts[2])

          self.timesteps.append(timestep)
          self.total_count.append(total_count)

          for i in range(num_chunks):
            self.chunks.append({
              'coord' : [],
              'ncount' : []
            })
        elif chunks_read < num_chunks:
          chunk = int(parts[0])
          ncount = float(parts[ncount_start])

          if compress:
            chunk_id = int(parts[1])
          else:
            chunk_id = chunk

          current = self.chunks[chunk_id - 1]
          current['id'] = chunk_id
          current['ncount'].append(ncount)

          if ndim > 0:
            coord = tuple(map(float, parts[coord_start:coord_end+1]))
            current['coord'].append(coord)

          for i, data_column in list(enumerate(columns))[data_start:]:
            value = float(parts[i])

            if data_column in current:
              current[data_column].append(value)
            else:
              current[data_column] = [value]

          chunks_read += 1
          assert chunk == chunks_read
        else:
          # do not support changing number of chunks
          if not (num_chunks == int(parts[1])):
            raise Exception("Currently, changing numbers of chunks are not supported.")

          timestep = int(parts[0])
          total_count = float(parts[2])
          chunks_read = 0

          self.timesteps.append(timestep)
          self.total_count.append(total_count)
