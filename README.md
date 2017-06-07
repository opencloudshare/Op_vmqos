# vmqos
set OpenStack Cloud based on OVS networking  VM's bandwidth (both ingress and egress) 

## PREPARING
```
pip install tornado==4.4.1 paramiko ConfigParser
```

and OpenStack SDK

## STARTING
- fill in or rewrite **host_conf** , it's a config file for all hypervisor hosts

- modify vmqos.py line 44-46 to suit your environment or just keep it as default

- modify vmqos.py line 69-75 to satisfy your requirement or keep it as default
- 
```
python vmqos.py -log_file_prefix=qos.log &
```
## VERIFYING


```
python >
>>> import requests
>>> url = 'http://controller:39697/setqos'
>>> send = {'username': 'youropenstackuser', 'vm_bandwidth': '20', 'password': 'youropenstackpassword', 'vm_uuid': '84b85be8-982a-49b9-94b6-3e6bdc241712', 'vm_project_uuid': '761c51d7f6404877bc03b8644e2cf428'}
>>> r = requests.post(url,send);r.text
```

```
{    
     "msg": "set qos success",
     "code": 2000
}
```
you can check hypervisor_host in log_file like

```
compute2 674778d7-b2
```
means the vm in your request is build on **compute2** and its virtual NIC device id is **674778d7-b2** ,lets ssh **compute2** and see NIC tc policy

```
$ tc qdisc list dev qvb674778d7-b2
qdisc htb 1: root refcnt 2 r2q 10 default 100 direct_packets_stat 0
qdisc sfq 81bf: parent 1:1 limit 127p quantum 1464b depth 127 divisor 1024 perturb 10sec 
qdisc sfq 81c1: parent 1:100 limit 127p quantum 1464b depth 127 divisor 1024 perturb 10sec 
qdisc sfq 81c3: parent 1:101 limit 127p quantum 1464b depth 127 divisor 1024 perturb 10sec
$ tc class list dev qvb674778d7-b2
class htb 1:101 root leaf 81c3: prio 0 rate 100000Kbit ceil 100000Kbit burst 12800Kb cburst 1600b 
class htb 1:100 root leaf 81c1: prio 0 rate 20000Kbit ceil 20000Kbit burst 2560Kb cburst 1600b 
class htb 1:1 root leaf 81bf: prio 0 rate 1000Mbit ceil 1000Mbit burst 1375b cburst 1375b
$ tc filter list dev qvb674778d7-b2
filter parent 1: protocol ip pref 1 u32 
filter parent 1: protocol ip pref 1 u32 fh 800: ht divisor 1 
filter parent 1: protocol ip pref 1 u32 fh 800::800 order 2048 key ht 800 bkt 0 flowid 1:101
```

setting tc policy succeed

## FURTHER
using tools like **iperf** and **netperf** to check real bandwidth 
- to/from private IP and public IP to see the difference if necessary