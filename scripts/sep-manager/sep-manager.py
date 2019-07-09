#!/usr/bin/env python

# Copyright (c) 2019 Omniga GmbH & Co. KG
#
# update SEP Sesam task with latest backup-paths
#

import json,shade,munch,datetime,logging,os,sys,paramiko

def promoteToIndex(dici, valueKey):
  import copy
  dic = copy.deepcopy(dici)
  rv = {}
  for row in dic:
      rv[row.pop(valueKey)] = row
  return rv

def chunks(l, n):
  # For item i in a range that is a length of l,
  for i in range(0, len(l), n):
    # Create an index range for l of n items:
    yield l[i:i+n]

## Load Config file
with open('/etc/sep-manager.json') as json_data_file:
  cfg = json.load(json_data_file)

## Get Project from args
p = sys.argv[1]

## See if external Auth is loadable or if we should use our own config
try:
  with open(cfg['auth']['external_file']) as json_data_file:
    ext_cfg = json.load(json_data_file)
  for e, v in ext_cfg['auth']['env_vars'].items():
    os.environ[e]=v
except:
  for e, v in cfg['auth']['env_vars'].items():
    os.environ[e]=v

## Connect to cloud
cloud = shade.openstack_cloud()
projects = promoteToIndex(cloud.list_projects(), 'name')
conn = cloud.connect_as(project_domain_id = projects[p]['domain_id'], project_name = p)

## basically do the same as cinder-easy-backup to gather the latest backups
## this is to prevent abandoned backups to be written onto tape
## might be more elegant to cycle through all backups and add the newest ones to a munch object

all_backups = conn.list_volume_backups()
to_backup = munch.Munch()
latest_backup = munch.Munch()

## get instances
instances = promoteToIndex(conn.list_servers(),'id')
for i in list(instances):
  ## Remove unwanted instances
  ## unless backup is explicitly set to false, assume true ## ignore instances without volumes
  if (instances[i]['metadata'].get('backup',True) == 'false') or (not instances[i]['volumes']):
    instances.pop(i)

## build volume dict
for i in instances:
  ## add every volume of an instance
  volumes = munch.Munch()
  for v in instances[i]['volumes']:
    vol = conn.get_volume_by_id(v['id'])
    ## unless backup is set to false
    if vol['metadata'].get('backup',True) != 'false':
      volumes[vol['id']] = vol

  ## cycle through volumes and collect backups
  for v in volumes:
    ## look for previous backups of this volume
    prev_backups = munch.Munch()
    for b in all_backups:
      if b['volume_id'] == v:
        prev_backups[b['id']] = b

    ## find newest backup and add it to list
    last_backup_time = datetime.datetime(datetime.MINYEAR,1,1)
    for pb in prev_backups:
      backup_date = datetime.datetime.strptime(prev_backups[pb]['created_at'], '%Y-%m-%dT%H:%M:%S.%f')
      if backup_date > last_backup_time:
        last_backup_time = backup_date
        latest_backup=prev_backups[pb]
    to_backup[latest_backup['id']]=latest_backup

## build path list for sep
paths = list()
for i in to_backup:
   paths.append(cfg['sep']['base_path'] + '/' + to_backup[i]['container'])

## sep paths can only be 254 chars long, so we need to split the array into smaller chunks
path_chunks = list(chunks(paths,3))

## connect to sep-server and create/update task
try:
  client = paramiko.SSHClient()
  client.load_system_host_keys()
  client.set_missing_host_key_policy(paramiko.WarningPolicy())

  client.connect(cfg['sep']['host'], port=cfg['sep']['ssh']['port'], username=cfg['sep']['ssh']['user'], password=cfg['sep']['ssh']['password'])

  for idx,val in enumerate(path_chunks):
    str_idx = str(idx).zfill(4)

    task_cmd = 'if ! '+ cfg['sep']['sm_cmd'] +' list task | grep '+ cfg['sep']['task_prefix'] +'_'+ str_idx +' > /dev/null; then '+ cfg['sep']['sm_cmd'] +' add task '+ cfg['sep']['task_prefix'] +'_'+ str_idx +' -c '+ cfg['sep']['client'] +' -G '+ cfg['sep']['timeplan'] +' -s /etc; fi'
    update_cmd = cfg['sep']['sm_cmd'] + ' modify task ' + cfg['sep']['task_prefix'] +'_'+ str_idx + ' -c ' + cfg['sep']['client'] + ' -s ' + ','.join(val)

    tsk_stdin, tsk_stdout, tsk_stderr = client.exec_command(task_cmd)
    tsk_stdout.readlines()

    upd_stdin, upd_stdout, upd_stderr = client.exec_command(update_cmd)
    upd_stdout.readlines()

finally:
  client.close()

