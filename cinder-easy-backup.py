#!/usr/bin/env python

# Copyright (c) 2019 Omniga GmbH & Co. KG
#
# create cinder backups on schedule
#

import json,shade,munch,datetime,logging,os,subprocess

def promoteToIndex(dici, valueKey):
  '''
  index the dic by valueKey.
  promotes the element on position <valueKey> from each sublist to an
  index in a dictionary.
  @param dic a list of lists or a list of dictionaries, e.g. a
   database result set.
  @param valueKey position or name of the value to be promoted to
   an index.
  @return promoted dictionary.
  example:
  >>> d = [[1,2,3,4,5], [6,7], [8,9], [9,10]] e=AspromScheduleModel.promoteToIndex(d,1) print e
  {9: [8], 2: [1, 3, 4, 5], 10: [9], 7: [6]}
  '''
  import copy
  dic = copy.deepcopy(dici)
  rv = {}
  for row in dic:
      rv[row.pop(valueKey)] = row
  return rv

## Load Config file
with open('/etc/cinder-easy-backup.json') as json_data_file:
  cfg = json.load(json_data_file)

## Set up Logger
logger = logging.getLogger('cinder-easy-backup')
logger.setLevel(logging.DEBUG)

fh = logging.FileHandler(cfg['log']['file'])
fh.setLevel(cfg['log']['level'])

ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)

formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
fh.setFormatter(formatter)
ch.setFormatter(formatter)

logger.addHandler(fh)
logger.addHandler(ch)

## Set up Credentials
for e, v in cfg['auth']['env_vars'].items():
  os.environ[e]=v

## Connect to cloud
cloud = shade.openstack_cloud()
projects = promoteToIndex(cloud.list_projects(), 'name')

## remove excluded projects
for p in cfg['backups']['excludes']['projects']:
  logger.info('Excluding Project ' + p + ' from Backup (set in cinder-easy-backup.json)')
  projects.pop(p)

## loop over remaining projects
for p in projects:

  ## set interval and retention for this project
  interval = cfg['backups']['interval']['backup']['project_override'].get(p,cfg['backups']['interval']['backup']['default'])
  abandon_interval = cfg['backups']['interval']['abandon']['project_override'].get(p,cfg['backups']['interval']['abandon']['default'])
  retention = cfg['backups']['retention']['project_override'].get(p,cfg['backups']['retention']['default'])
  wait_for_completion = cfg['backups']['wait_for_completion']['project_override'].get(p,cfg['backups']['wait_for_completion']['default'])

  ## connect to project
  conn = cloud.connect_as(project_domain_id = projects[p]['domain_id'], project_name = p)

  ## get available backups
  try:
    all_backups = promoteToIndex(conn.list_volume_backups(),'id')
  except:
    logger.warning('Skipping Project ' + p + ' (no permissions)')
    continue

  ## get instances
  instances = promoteToIndex(conn.list_servers(),'id')
  for i in list(instances):
    ## Remove unwanted instances
    ## unless backup is explicitly set to false, assume true ## ignore instances without volumes
    if (instances[i]['metadata'].get('backup',True) == 'false') or (not instances[i]['volumes']):
      logger.warning('Excluding Instance ' + instances[i]['name'] + ' from Backup (disabled via metadata or no volume attached)')
      instances.pop(i)

  ## build volume munch
  all_volumes = munch.Munch()
  for i in instances:
    ## add every volume of an instance
    for v in instances[i]['volumes']:
      vol = conn.get_volume_by_id(v['id'])
      ## unless backup is set to false or volume has no attachment
      if vol['metadata'].get('backup',True) == 'false':
        logger.warning('Excluding Volume ' + vol['id'] + ' attached to ' + instances[i]['name'] + ' (disabled via metadata)')
      elif len(vol['attachments']) < 1:
        logger.warning('Excluding Volume ' + vol['id'] + ' of ' + instances[i]['name'] + ' (not attached)')
      else:
        all_volumes[vol['id']] = vol

  ## cycle through volumes and create backups
  for volume_id,volume_data in all_volumes.items():
    ## look for previous backups of this volume
    prev_backups = munch.Munch()
    for backup_id,backup_data in all_backups.items():
      if backup_data['volume_id'] == volume_id:
        prev_backups[backup_id] = backup_data

    ## find newest backup and compare timestamps
    last_backup_time = datetime.datetime(datetime.MINYEAR,1,1)
    prev_backups
    for pbackup_id,pbackup_data in prev_backups.items():
      backup_date = datetime.datetime.strptime(pbackup_data['created_at'], '%Y-%m-%dT%H:%M:%S.%f')
      if backup_date > last_backup_time:
        last_backup_time = backup_date

    ## make backup
    now = datetime.datetime.now()
    last_backup_age_days = round((now-last_backup_time).total_seconds()/60/60/24,2)
    instance_id = volume_data['attachments'][0]['server_id']
    if last_backup_age_days >= interval:
      backup_name = instances[instance_id]['name'] + '_' + volume_id + '_' + now.strftime("%Y-%m-%dT%H-%M-%S")
      logger.info('Creating Backup ' + backup_name + ' (last backup ' + str(last_backup_age_days) + ' days ago)')
      try:
        conn.create_volume_backup(volume_id,name=backup_name,force=True,wait=wait_for_completion)
        backup_created = True
      except Exception as e:
        logger.error('Backup ' + backup_name + ' failed: ' + str(e))
        backup_created = False
        continue
    else:
      logger.info('Skipping Volume ' + instances[instance_id]['name'] + ':' + volume_id + ' (below interval)')
      backup_created = False

    ## find oldest backup(s) and delete
    ## len(prev_backups) is missing newly created backups so we use int(backup_created) to add 1 to it in case a backup was created or 0 if none was created
    ## this ensures that always 'retention'-number of backups are kept
    while len(prev_backups) + int(backup_created) > retention:
      oldest_backup_time = datetime.datetime(datetime.MAXYEAR,1,1)
      backup_to_delete = munch.Munch()
      for pbackup_id,pbackup_data in prev_backups.items():
        backup_date = datetime.datetime.strptime(pbackup_data['created_at'], '%Y-%m-%dT%H:%M:%S.%f')
        if backup_date < oldest_backup_time:
          oldest_backup_time = backup_date
          backup_to_delete = pbackup_id
      try:
        conn.delete_volume_backup(backup_to_delete)
        logger.info('Deleted Backup: ' + backup_to_delete)
      except Exception as e:
        logger.error('Deletion of Backup ' + backup_to_delete + ' failed: ' + str(e))
      prev_backups.pop(backup_to_delete)

  ## find abandoned backups and delete
  ## loop over all backups and check if its volume_id is missing in all_volumes
  abandoned_backups = munch.Munch()
  now = datetime.datetime.now()
  for backup_id, backup_data in all_backups.items():
    if not backup_data['volume_id'] in all_volumes:
      abandoned_backup_date = datetime.datetime.strptime(str(backup_data['created_at']), '%Y-%m-%dT%H:%M:%S.%f')
      abandoned_backup_age_days = round((now-abandoned_backup_date).total_seconds()/60/60/24,2)
      ## delete abandoned Backups
      if abandoned_backup_age_days >= abandon_interval:
        try:
          conn.delete_volume_backup(backup_id)
          logger.info('Deleted abandoned Backup : ' + backup_data['name'] + ' (Instance missing for ' + str(abandoned_backup_age_days) + ' Days)')
        except Exception as e:
          logger.error('Deletion of Backup ' + backup_data['name'] + ' failed: ' + str(e))

  ## run post-script for current env
  try:
    cfg['backups']['post_script'][p]
    post_cmd = cfg['backups']['post_script'][p] + ' ' + p
    try:
      logger.info('Running Post-Script: ' + post_cmd )
      subprocess.check_call(post_cmd, shell=True)
    except:
      logger.error('Post-Script for ' + p + ' failed. Command: ' + post_cmd)
  except KeyError:
    logger.info('No Post-Script for ' + p)
