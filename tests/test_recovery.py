"""No live API: synthetic metadata/logs only, mock every provenance fetch."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock
from urllib.request import Request

from ci import recovery as r
from ci.contract import validate
from test_workflow import evaluate
from ci.workflow_policy import condition, job

ROOT = Path(__file__).resolve().parents[1]


def control(root):
    return dict(GITHUB_REPOSITORY=r.REPO, GITHUB_EVENT_NAME='workflow_dispatch',
                GITHUB_REF='refs/heads/main', GITHUB_ACTOR='myachmen', GITHUB_TRIGGERING_ACTOR='myachmen',
                GITHUB_RUN_ID='999999', GITHUB_RUN_ATTEMPT='1', GITHUB_SHA='a'*40,
                GITHUB_WORKFLOW_REF=r.REPO+'/'+r.RECOVERY_WORKFLOW+'@refs/heads/main',
                GITHUB_WORKFLOW_SHA='a'*40, RECOVERY_CONFIRMATION=r.CONFIRM, RUNNER_TEMP=str(root),
                GH_TOKEN='synthetic-private-token', CD_RECOVERY='origin-26',
                ORIGIN_BUILD_RUN_ID=str(r.ORIGIN), EXECUTION_RUN_ID='999999',
                BUILD_RESULT='success', IMAGE_DIGEST=r.DIGEST, SOURCE_SHA=r.SHA,
                SOURCE_TAG=r.TAG, SOURCE_RUN=str(r.ORIGIN), APP_VERSION=r.VERSION)


def fixtures():
    run = dict(id=r.ORIGIN, run_number=26, run_attempt=1, repository={'full_name':r.REPO},
               event='push', head_sha=r.SHA, head_branch=r.TAG, path=r.WORKFLOW,
               conclusion='failure', status='completed')
    jobs = {'total_count':3, 'jobs':[]}
    for name, number in r.JOBS.items():
        conclusion = 'failure' if name=='deploy' else 'success'
        step = 'Deploy this run digest and verify application' if name=='deploy' else 'Build and push exact source'
        jobs['jobs'].append(dict(id=number,name=name,run_id=r.ORIGIN,run_attempt=1,head_sha=r.SHA,
                                status='completed',conclusion=conclusion,
                                steps=[dict(name=step,conclusion=conclusion,status='completed')]))
    source = {'BUILD_RESULT':'success','IMAGE_DIGEST':r.DIGEST,'SOURCE_SHA':r.SHA,
              'SOURCE_TAG':r.TAG,'SOURCE_RUN':str(r.ORIGIN),'APP_VERSION':r.VERSION}
    deploy = '2026-11-07T12:00:00.000Z ##[group]Run bash ci/deploy.sh\n'
    deploy += '\n'.join('2026-11-07T12:00:00.000Z   '+k+': '+v for k,v in source.items())+'\n'
    deploy += ('Same-run release contract PASS\n'
               'API_ACCESS FAIL attempt=1/10 category=API_CONNECTION_FAILURE process=running exit=1\n'
               'API_ACCESS FAIL attempt=2/10 category=API_CONNECTION_FAILURE process=running exit=1\n'
               'API_ACCESS FAIL attempt=3/10 category=API_AUTH_401 process=running exit=1\n'
               'CD FAIL stage=ssh_api_access exit=1; STOP, no retry/rollback\n'
               'Process completed with exit code 1\nPost job cleanup\n')
    tag = {'ref':'refs/tags/'+r.TAG, 'object':{'type':'commit','sha':r.SHA,
           'url':'https://api.github.com/repos/'+r.REPO+'/git/commits/'+r.SHA}}
    return [run,jobs,'"containerimage.digest": "'+r.DIGEST+'"',deploy,tag]


class Recovery(unittest.TestCase):
    def test_original_evidence_and_private_execution_bound_manifest(self):
        values=fixtures()
        with tempfile.TemporaryDirectory() as tmp:
            env=control(tmp);get=Mock(side_effect=[values[0],values[1],values[2],values[3],values[4]])
            doc=r.verify_and_write(env,get=get)
            self.assertEqual(doc['origin_build_run_id'],str(r.ORIGIN))
            self.assertNotEqual(doc['execution_run_id'],str(r.ORIGIN))
            self.assertEqual(validate(env),'1.0.4')
            self.assertEqual(r.manifest_path(env).stat().st_mode & 0o777,0o600)
            self.assertEqual(get.call_count,5)
            self.assertTrue(all('repos/' not in c.args[0] for c in get.call_args_list))
            with self.assertRaises(FileExistsError):r.verify_and_write(env,get=Mock(side_effect=values))

    def test_origin_metadata_negative_cases(self):
        changes=[('id',1),('run_number',25),('run_attempt',2),('repository',{'full_name':'fork/app'}),
                 ('event','pull_request'),('head_sha','b'*40),('head_branch','v9.9.9'),
                 ('path','other.yml'),('conclusion','success'),('status','in_progress')]
        for k,v in changes:
            f=fixtures();f[0][k]=v
            with self.subTest(k=k),self.assertRaises(ValueError):r.evidence(*f)

    def test_wrong_job_attempt_status_or_step_and_ambiguous_jobs(self):
        for k,v in [('id',1),('run_id',1),('run_attempt',2),('head_sha','b'*40),
                    ('conclusion','skipped'),('status','in_progress'),('steps',[])]:
            f=fixtures();f[1]['jobs'][1][k]=v
            with self.subTest(k=k),self.assertRaises(ValueError):r.evidence(*f)
        f=fixtures();f[1]['jobs'][2]['conclusion']='skipped'
        with self.assertRaises(ValueError):r.evidence(*f)
        f=fixtures();f[1]['jobs'].append(deepcopy(f[1]['jobs'][1]));f[1]['total_count']=4
        with self.assertRaises(ValueError):r.evidence(*f)

    def test_missing_masked_changed_or_ambiguous_digest_and_source(self):
        for index in [2,3]:
            for replacement in ['', '***','sha256:'+'c'*64]:
                f=fixtures();f[index]=f[index].replace(r.DIGEST,replacement)
                with self.subTest(index=index,replacement=replacement),self.assertRaises(ValueError):r.evidence(*f)
        for k,v in [('SOURCE_SHA','b'*40),('SOURCE_RUN','555'),('SOURCE_TAG','v9.9.9'),
                    ('APP_VERSION','9.9.9'),('BUILD_RESULT','skipped')]:
            f=fixtures();f[3]=f[3].replace(k+': '+control('/tmp')[k], k+': '+v)
            with self.subTest(k=k),self.assertRaises(ValueError):r.evidence(*f)
        for index in [2,3]:
            f=fixtures();f[index]+=f[index]
            with self.assertRaises(ValueError):r.evidence(*f)

    def test_unknown_or_after_patch_boundary_and_changed_tag_fail_closed(self):
        for text in ['API_AUTH_401','Same-run release contract PASS','stage=ssh_api_access',
                     'Process completed with exit code 1']:
            f=fixtures();f[3]=f[3].replace(text,'unknown')
            with self.subTest(text=text),self.assertRaises(ValueError):r.evidence(*f)
        for text in ['CD PASS','API_ACCESS PASS','stage=guarded_patch','stage=rollout','stage=http_smoke']:
            f=fixtures();f[3]=f[3].replace('Post job cleanup',text+'\nPost job cleanup')
            with self.assertRaises(ValueError):r.evidence(*f)
        f=fixtures();f[4]['object']['sha']='b'*40
        with self.assertRaises(ValueError):r.evidence(*f)

    def test_execution_cross_run_ref_actor_confirmation_and_output_substitution(self):
        with tempfile.TemporaryDirectory() as tmp:
            env=control(tmp);r.verify_and_write(env,get=Mock(side_effect=fixtures()))
            changes=[('GITHUB_EVENT_NAME','push'),('GITHUB_EVENT_NAME','pull_request'),
                     ('GITHUB_REF','refs/heads/feature/x'),('GITHUB_REF','refs/tags/v1.0.4'),
                     ('GITHUB_REPOSITORY','fork/app'),('GITHUB_ACTOR','other'),
                     ('GITHUB_TRIGGERING_ACTOR','other'),('GITHUB_RUN_ATTEMPT','2'),
                     ('GITHUB_RUN_ID',str(r.ORIGIN)),('GITHUB_RUN_ID','8888'),
                     ('GITHUB_WORKFLOW_SHA','b'*40),('GITHUB_WORKFLOW_REF','other'),
                     ('GITHUB_SHA','b'*40),('RECOVERY_CONFIRMATION',''),('ORIGIN_BUILD_RUN_ID','1'),
                     ('EXECUTION_RUN_ID','1'),('SOURCE_RUN','1'),('IMAGE_DIGEST','sha256:'+'b'*64),
                     ('BUILD_RESULT','skipped'),('APP_VERSION','9.9.9'),('CD_RECOVERY','unknown')]
            for k,v in changes:
                with self.subTest(k=k),self.assertRaises(ValueError):validate(dict(env,**{k:v}))
            r.manifest_path(env).chmod(0o644)
            with self.assertRaises(ValueError):validate(env)

    def test_invalid_manifest_rejects_before_external_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            env=control(tmp);marker=Path(tmp)/'called'
            for name in ['ssh','kubectl','curl']:
                p=Path(tmp)/name;p.write_text('#!/bin/sh\necho called >> "'+str(marker)+'"\nexit 99\n');p.chmod(0o700)
            env.update(PATH=tmp+os.pathsep+os.environ['PATH'])
            result=subprocess.run(['bash','ci/deploy.sh'],cwd=ROOT,env=dict(os.environ,**env),
                                  capture_output=True,text=True,timeout=5)
            self.assertNotEqual(result.returncode,0);self.assertFalse(marker.exists())
            self.assertNotIn('synthetic-private-token',result.stdout+result.stderr)

    def test_api_redirect_never_forwards_github_credentials(self):
        original=Request('https://api.github.com/repos/'+r.REPO+'/actions/jobs/1/logs',
                         headers={'Authorization':'Bearer synthetic-private-token'})
        target=r.NoCredentialRedirect().redirect_request(original,None,302,'',{},'https://logs.example.invalid/signed')
        self.assertNotIn('Authorization',target.headers)
        for url in ['http://logs.example.invalid/','https://user:password@logs.example.invalid/']:
            with self.assertRaises(ValueError):r.NoCredentialRedirect().redirect_request(original,None,302,'',{},url)

    def test_workflow_manual_only_pins_permissions_no_registry_and_shared_writer(self):
        text=(ROOT/r.RECOVERY_WORKFLOW).read_text()
        self.assertIn('  workflow_dispatch:',text)
        for bad in ['  push:','  pull_request:','  workflow_run:', 'YC_SA_KEY_JSON', 'docker/', 'actions: write']:
            self.assertNotIn(bad,text)
        self.assertIn('permissions: {}',text)
        self.assertIn('      actions: read',text)
        self.assertIn('      contents: read',text)
        self.assertIn('group: diploma-app-run-production',text)
        self.assertIn('group: diploma-app-production',text)
        self.assertLess(text.index('python3 -m ci.recovery --verify'),text.index('secrets.CD_KUBE_TOKEN'))
        for event in ['push','pull_request','workflow_dispatch']:
            for ref in ['refs/heads/main','refs/heads/feature/x','refs/tags/v1.0.4']:
                for attempt in [1,2]:
                    values={'github.repository':r.REPO,'github.event_name':event,'github.ref':ref,
                            'github.actor':'myachmen','github.triggering_actor':'myachmen','github.run_attempt':attempt}
                    self.assertEqual(evaluate(condition(job(text,'recover')),values),
                                     event=='workflow_dispatch' and ref=='refs/heads/main' and attempt==1)
