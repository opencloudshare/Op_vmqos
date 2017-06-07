# -*- coding:utf-8 -*-
import tornado.httpserver
import tornado.ioloop
import tornado.options
import tornado.web
import logging

import tornado.gen
from tornado.concurrent import run_on_executor
from concurrent.futures import ThreadPoolExecutor

import json
import time
import os
import paramiko
import ConfigParser

from keystoneauth1 import identity
from keystoneauth1 import session
from novaclient import client

from tornado.options import define, options
define("port", default=39697, help="run on the given port", type=int)



class Application(tornado.web.Application):
    def __init__(self):
        handlers = [(r"/setqos", SetqosHandler)]
        
        tornado.web.Application.__init__(self, handlers, debug=True)

class SetqosHandler(tornado.web.RequestHandler):
    executor = ThreadPoolExecutor(8)
    @tornado.web.asynchronous
    @tornado.gen.coroutine
    def post(self):
        # get value from request and default setting
        username = self.get_body_argument("username")
        password= self.get_body_argument("password")
        project_id = self.get_body_argument("vm_project_uuid")
        vm_uuid = self.get_body_argument("vm_uuid")
        vm_bandwidth = self.get_body_argument("vm_bandwidth")
        auth_url = 'http://controller:35357/v3'
        project_domain_id = 'default'
        user_domain_id = 'default'
        
        log_time = time.ctime()
        logging.info(log_time+" "+project_id+" "+vm_uuid+" "+vm_bandwidth)
        # get OpenStack session and acquire VM's info we need via Nova-api
        nova_kwargs = {
            'auth_url': auth_url,
            'username': username,
            'password': password,
            'project_id': project_id,
            'project_domain_id': project_domain_id,
            'user_domain_id': user_domain_id
        }
        nova = yield self.nova_client(**nova_kwargs)
        # vm's hypervisor hostname and interface id(virtual NIC device_id)
        hypervisor_host = nova.servers.get(vm_uuid).__dict__['OS-EXT-SRV-ATTR:host']
        device_id = nova.servers.get(vm_uuid).interface_list()[0].id[0:11]
        logging.info(hypervisor_host+' '+device_id)

        # rx means  inbound/download traffic, tx means outbound/upload traffic 
        # modify ceil_bandwidth and burst_flow as you like
        rx_device = 'qvo'+device_id
        tx_device = 'qvb'+device_id
        ceil_bandwidth = vm_bandwidth
        burst_flow = vm_bandwidth
        
        # bandwidth to/from  VPC inside , default is 100
        inner_bandwidth = '100'
        inner_ceil = '100'
        inner_burst = '100'

        if vm_bandwidth == '0':
            set_vm_rx = "tc qdisc del dev {rx_device} root".format(rx_device=rx_device)
            set_vm_tx = "tc qdisc del dev {tx_device} root".format(tx_device=tx_device)
            logging.info("clear qos policy")
        else:
            set_vm_rx = '''tc qdisc del dev {rx_device} root;
                         tc qdisc add dev {rx_device} root handle 1: htb default 100;
                         tc class add dev {rx_device} parent 1: classid 1:1 htb rate 1gbit;
                         tc qdisc add dev {rx_device} parent 1:1 sfq perturb 10;
                         tc class add dev {rx_device} parent 1: classid 1:100 htb rate {vm_bandwidth}mbit ceil {ceil_bandwidth}mbit burst {burst_flow}mbit;
                         tc qdisc add dev {rx_device} parent 1:100 sfq perturb 10;
                         tc class add dev {rx_device} parent 1: classid 1:101 htb rate {inner_bandwidth}mbit ceil {inner_ceil}mbit burst {inner_burst}mbit;
                         tc qdisc add dev {rx_device} parent 1:101 sfq perturb 10;
                         tc filter add dev {rx_device} protocol ip parent 1: prio 1 u32 match ip src 10.0.0.0/8 flowid 1:101;'''.format(rx_device=rx_device,vm_bandwidth=vm_bandwidth,ceil_bandwidth=ceil_bandwidth,burst_flow=burst_flow,inner_bandwidth=inner_bandwidth,inner_ceil=inner_ceil,inner_burst=inner_burst)
        
            set_vm_tx = '''tc qdisc del dev {tx_device} root;
                         tc qdisc add dev {tx_device} root handle 1: htb default 100;
                         tc class add dev {tx_device} parent 1: classid 1:1 htb rate 1gbit;
                         tc qdisc add dev {tx_device} parent 1:1 sfq perturb 10;
                         tc class add dev {tx_device} parent 1: classid 1:100 htb rate {vm_bandwidth}mbit ceil {ceil_bandwidth}mbit burst {burst_flow}mbit;
                         tc qdisc add dev {tx_device} parent 1:100 sfq perturb 10;
                         tc class add dev {tx_device} parent 1: classid 1:101 htb rate {inner_bandwidth}mbit ceil {inner_ceil}mbit burst {inner_burst}mbit;
                         tc qdisc add dev {tx_device} parent 1:101 sfq perturb 10;
                         tc filter add dev {tx_device} protocol ip parent 1: prio 1 u32 match ip dst 10.0.0.0/8 flowid 1:101;'''.format(tx_device=tx_device,vm_bandwidth=vm_bandwidth,ceil_bandwidth=ceil_bandwidth,burst_flow=burst_flow,inner_bandwidth=inner_bandwidth,inner_ceil=inner_ceil,inner_burst=inner_burst)

        ssh_kwargs = yield self.get_ssh_info(hypervisor_host)
        logging.info(str(ssh_kwargs))
        ssh_kwargs['set_vm_rx'] = set_vm_rx
        ssh_kwargs['set_vm_tx'] = set_vm_tx
        msg = yield self.ssh_exec(**ssh_kwargs)

        msg_js = json.dumps(msg,indent=4)
        self.write(msg_js)
        self.finish()

    @run_on_executor
    def nova_client(self,auth_url,username,password,project_id,project_domain_id,user_domain_id):
        auth = identity.Password(auth_url=auth_url,
                                 username=username,
                                 password=password,
                                 project_id=project_id,
                                 project_domain_id=project_domain_id,
                                 user_domain_id=user_domain_id)
        sess = session.Session(auth=auth)
        nova = client.Client("2.1",session=sess)
        return nova


    # read ssh info from file
    @run_on_executor
    def get_ssh_info(self,hypervisor_host):
        try:
            cf = ConfigParser.ConfigParser()
            cf.read(os.path.join(os.getcwd(),"host_conf"))
            ssh_host = cf.get(hypervisor_host,"ip")
            ssh_port = int(cf.get(hypervisor_host,"port"))
            ssh_user = cf.get(hypervisor_host,"user")
            ssh_password = cf.get(hypervisor_host,"password")
            ssh_kwargs = {
                'ssh_host' : ssh_host,
                'ssh_port' : ssh_port,
                'ssh_user' : ssh_user,
                'ssh_password' : ssh_password
            }
            return ssh_kwargs
        except Exception,e:
            logging.info("host_conf file read error"+str(e))
            return 0
    # ssh to hypervisor_host where virtual NIC device is bound, and write tc policy
    @run_on_executor
    def ssh_exec(self,ssh_host,ssh_port,ssh_user,ssh_password,set_vm_rx,set_vm_tx):
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(ssh_host,ssh_port,ssh_user,ssh_password)
            stdin, stdout, stderr = ssh.exec_command(set_vm_rx)
            stdin, stdout, stderr = ssh.exec_command(set_vm_tx)
            ssh.close()
            msg = {'code':2000,'msg':'set qos success'}
        except Exception,e:
            logging.info("ssh error "+str(e))
            msg = {'code':5000,'msg':'error happend,please check detail log'}
        return msg

if __name__ == "__main__":
    tornado.options.parse_command_line()
    logging.debug("debug ...")
    http_server = tornado.httpserver.HTTPServer(Application())
    http_server.listen(options.port)
    tornado.ioloop.IOLoop.instance().start()

