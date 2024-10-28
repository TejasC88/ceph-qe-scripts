"""
Usage: test_cors_using_curl.py -c <input_yaml>
polarion: CEPH-10355
<input_yaml>
    Note: Following yaml can be used
    test_cors_using_curl.yaml
    
Operation:
    Test CORS on a bucket using CURL API calls.
"""


import argparse
import json
import logging
import os
import sys
import traceback

sys.path.append(os.path.abspath(os.path.join(__file__, "../../../..")))


from v2.lib import resource_op
from v2.lib.aws import auth as aws_auth
from v2.lib.aws.resource_op import AWS
from v2.lib.curl.resource_op import CURL
from v2.lib.exceptions import RGWBaseException, TestExecError
from v2.lib.s3.write_io_info import BasicIOInfoStructure, IOInfoInitialize
from v2.tests.aws import reusable as aws_reusable
from v2.tests.curl import reusable as curl_reusable
from v2.tests.s3_swift import reusable as s3_reusable
from v2.utils import utils
from v2.utils.log import configure_logging
from v2.utils.test_desc import AddTestInfo

log = logging.getLogger(__name__)
TEST_DATA_PATH = None


def test_exec(config, ssh_con):
    """
    Executes test based on configuration passed
    Args:
        config(object): Test configuration
    """
    io_info_initialize = IOInfoInitialize()
    basic_io_structure = BasicIOInfoStructure()
    io_info_initialize.initialize(basic_io_structure.initial())

    curl_reusable.install_curl(version="7.88.1")
    all_users_info = resource_op.create_users(no_of_users_to_create=config.user_count)

    for each_user in all_users_info:
        user_name = each_user["user_id"]
        log.info(user_name)
        cli_aws = AWS(ssl=config.ssl)
        endpoint = aws_reusable.get_endpoint(ssh_con, ssl=config.ssl)
        aws_auth.do_auth_aws(each_user)
        curl_auth = CURL(each_user, ssh_con, ssl=config.ssl)

        for bc in range(config.bucket_count):
            bucket_name = utils.gen_bucket_name_from_userid(user_name, rand_no=bc)
            curl_reusable.create_bucket(curl_auth, bucket_name)
            log.info(f"Bucket {bucket_name} created")
            log.info(f"Put CORS configuration for bucket {bucket_name}")
            file_name = "cors.json"
            cors_policy = json.dumps(config.test_ops["policy_document"])
            log.info(cors_policy)
            with open(file_name, "a") as f:
                f.write(cors_policy)
            aws_reusable.put_bucket_cors(cli_aws, bucket_name, file_name, endpoint)
            cors_origin = config.test_ops["cors_origin"]
            log.info(f"Origin : {cors_origin}")
            log.info("Test cURL PUT,GET and DELETE with mentioned origin")
            # create objects
            objects_created_list = []
            # uploading data
            log.info(f"s3 objects to create: {config.objects_count}")
            for oc, size in list(config.mapped_sizes.items()):
                config.obj_size = size
                s3_object_name = utils.gen_s3_object_name(bucket_name, oc)
                log.info(f"s3 object name: {s3_object_name}")
                s3_object_path = os.path.join(TEST_DATA_PATH, s3_object_name)
                log.info(f"s3 object path: {s3_object_path}")
                curl_reusable.put_cors_object(
                    curl_auth,
                    bucket_name,
                    s3_object_name,
                    TEST_DATA_PATH,
                    config,
                    cors_origin,
                )
                objects_created_list.append(s3_object_name)
                curl_reusable.download_object(
                    curl_auth,
                    bucket_name,
                    s3_object_name,
                    TEST_DATA_PATH,
                    s3_object_path,
                    cors_origin,
                )
                curl_reusable.delete_object(
                    curl_auth,
                    bucket_name,
                    s3_object_name,
                    cors_origin,
                )
            if config.local_file_delete is True:
                log.info("deleting local file created after the upload")
                utils.exec_shell_cmd(f"rm -rf  {s3_object_path}")
        if config.user_remove:
            s3_reusable.remove_user(each_user)

    # check for any crashes during the execution
    crash_info = s3_reusable.check_for_crash()
    if crash_info:
        raise TestExecError("ceph daemon crash found!")


if __name__ == "__main__":
    test_info = AddTestInfo("test rgw operations using curl")

    try:
        project_dir = os.path.abspath(os.path.join(__file__, "../../.."))
        test_data_dir = "test_data"
        TEST_DATA_PATH = os.path.join(project_dir, test_data_dir)
        log.info(f"TEST_DATA_PATH: {TEST_DATA_PATH}")
        if not os.path.exists(TEST_DATA_PATH):
            log.info("test data dir not exists, creating.. ")
            os.makedirs(TEST_DATA_PATH)
        parser = argparse.ArgumentParser(description="Test bucket CORS using Curl")
        parser.add_argument("-c", dest="config", help="RGW Test yaml configuration")
        parser.add_argument(
            "-log_level",
            dest="log_level",
            help="Set Log Level [DEBUG, INFO, WARNING, ERROR, CRITICAL]",
            default="info",
        )
        parser.add_argument(
            "--rgw-node", dest="rgw_node", help="RGW Node", default="127.0.0.1"
        )
        args = parser.parse_args()
        yaml_file = args.config
        rgw_node = args.rgw_node
        ssh_con = None
        if rgw_node != "127.0.0.1":
            ssh_con = utils.connect_remote(rgw_node)
        log_f_name = os.path.basename(os.path.splitext(yaml_file)[0])
        configure_logging(f_name=log_f_name, set_level=args.log_level.upper())
        config = resource_op.Config(yaml_file)
        config.read(ssh_con)
        if config.mapped_sizes is None:
            config.mapped_sizes = utils.make_mapped_sizes(config)

        test_exec(config, ssh_con)
        test_info.success_status("test passed")
        sys.exit(0)

    except (RGWBaseException, Exception) as e:
        log.error(e)
        log.error(traceback.format_exc())
        test_info.failed_status("test failed")
        sys.exit(1)

    finally:
        utils.cleanup_test_data_path(TEST_DATA_PATH)
