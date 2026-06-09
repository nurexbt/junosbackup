"""Seed sample Juniper devices and configs into the running app."""
import requests

BASE = 'http://localhost:5000'

# ── Devices ───────────────────────────────────────────────────────────────────
devices = [
    {'hostname': 'core-router-01', 'ip_address': '10.0.0.1',
     'model': 'MX480', 'location': 'DC-1 Rack 3', 'description': 'Core internet router'},
    {'hostname': 'edge-router-02', 'ip_address': '10.0.0.2',
     'model': 'MX204', 'location': 'DC-1 Rack 5', 'description': 'Edge peering router'},
    {'hostname': 'access-sw-01',   'ip_address': '10.0.1.1',
     'model': 'EX4300', 'location': 'DC-2 Rack 1', 'description': 'Access layer switch'},
]

ids = {}
for d in devices:
    r = requests.post(f'{BASE}/api/devices', json=d)
    if r.status_code in (200, 201):
        ids[d['hostname']] = r.json()['id']
        print(f"  Device added: {d['hostname']} (id={ids[d['hostname']]})")
    elif r.status_code == 409:
        # already exists – fetch id
        devs = requests.get(f'{BASE}/api/devices').json()
        for dev in devs:
            if dev['hostname'] == d['hostname']:
                ids[d['hostname']] = dev['id']
        print(f"  Device exists: {d['hostname']} (id={ids[d['hostname']]})")
    else:
        print(f"  ERROR adding {d['hostname']}: {r.text}")

# ── Configs ───────────────────────────────────────────────────────────────────
cfg_base = """\
version 22.4R1.10;
system {
    host-name core-router-01;
    domain-name corp.example.com;
    time-zone UTC;
    root-authentication {
        encrypted-password "$6$abc123";
    }
    services {
        ssh {
            root-login deny;
            protocol-version v2;
        }
        netconf { ssh; }
    }
    syslog {
        host 10.0.10.5 { any notice; authorization info; }
        file messages { any notice; authorization info; }
    }
    ntp {
        server 10.0.10.1;
        server 10.0.10.2;
    }
}
interfaces {
    ge-0/0/0 {
        description "Uplink to ISP-A";
        unit 0 { family inet { address 203.0.113.1/30; } }
    }
    ge-0/0/1 {
        description "Core LAN";
        unit 0 { family inet { address 10.0.0.1/24; } }
    }
    lo0 {
        unit 0 { family inet { address 192.168.255.1/32; } }
    }
}
routing-options {
    static { route 0.0.0.0/0 next-hop 203.0.113.2; }
    router-id 192.168.255.1;
    autonomous-system 65001;
}
protocols {
    bgp {
        group ISP-A {
            type external;
            peer-as 64512;
            neighbor 203.0.113.2 { description "ISP-A Peering"; }
        }
    }
    ospf {
        area 0.0.0.0 {
            interface ge-0/0/1.0;
            interface lo0.0 { passive; }
        }
    }
}
policy-options {
    prefix-list MGMT-HOSTS { 10.0.10.0/24; }
    policy-statement EXPORT-TO-ISP {
        term ALLOW-OWN {
            from { protocol static; route-filter 10.0.0.0/8 orlonger; }
            then accept;
        }
        term DENY-REST { then reject; }
    }
}
firewall {
    filter PROTECT-RE {
        term ALLOW-MGMT {
            from { source-prefix-list MGMT-HOSTS; protocol tcp; destination-port ssh; }
            then accept;
        }
        term ALLOW-OSPF { from { protocol ospf; } then accept; }
        term ALLOW-BGP  { from { protocol tcp; destination-port bgp; } then accept; }
        term DENY-ALL   { then { discard; log; } }
    }
}
"""

cfg_updated = """\
version 22.4R1.10;
system {
    host-name core-router-01;
    domain-name corp.example.com;
    time-zone UTC;
    root-authentication {
        encrypted-password "$6$abc123";
    }
    services {
        ssh {
            root-login deny;
            protocol-version v2;
        }
        netconf { ssh; }
    }
    syslog {
        host 10.0.10.5 { any notice; authorization info; }
        file messages { any notice; authorization info; }
    }
    ntp {
        server 10.0.10.1;
        server 10.0.10.2;
        server 10.0.10.3;
    }
}
interfaces {
    ge-0/0/0 {
        description "Uplink to ISP-A";
        unit 0 { family inet { address 203.0.113.1/30; } }
    }
    ge-0/0/1 {
        description "Core LAN - updated";
        unit 0 { family inet { address 10.0.0.1/24; } }
    }
    ge-0/0/2 {
        description "Secondary uplink ISP-B";
        unit 0 { family inet { address 198.51.100.1/30; } }
    }
    lo0 {
        unit 0 { family inet { address 192.168.255.1/32; } }
    }
}
routing-options {
    static { route 0.0.0.0/0 next-hop 203.0.113.2; }
    router-id 192.168.255.1;
    autonomous-system 65001;
}
protocols {
    bgp {
        group ISP-A {
            type external;
            peer-as 64512;
            neighbor 203.0.113.2 { description "ISP-A Peering"; }
        }
        group ISP-B {
            type external;
            peer-as 64513;
            neighbor 198.51.100.2 { description "ISP-B Peering - new"; }
        }
    }
    ospf {
        area 0.0.0.0 {
            interface ge-0/0/1.0;
            interface lo0.0 { passive; }
        }
    }
}
policy-options {
    prefix-list MGMT-HOSTS { 10.0.10.0/24; }
    policy-statement EXPORT-TO-ISP {
        term ALLOW-OWN {
            from { protocol static; route-filter 10.0.0.0/8 orlonger; }
            then accept;
        }
        term DENY-REST { then reject; }
    }
}
firewall {
    filter PROTECT-RE {
        term ALLOW-MGMT {
            from { source-prefix-list MGMT-HOSTS; protocol tcp; destination-port ssh; }
            then accept;
        }
        term ALLOW-OSPF { from { protocol ospf; } then accept; }
        term ALLOW-BGP  { from { protocol tcp; destination-port bgp; } then accept; }
        term DENY-ALL   { then { discard; log; } }
    }
}
"""

cfg_edge = """\
set system host-name edge-router-02
set system domain-name corp.example.com
set system time-zone UTC
set system services ssh root-login deny
set system services ssh protocol-version v2
set system services netconf ssh
set system ntp server 10.0.10.1
set system ntp server 10.0.10.2
set interfaces ge-0/0/0 description "Uplink to core"
set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.2/24
set interfaces ge-0/0/1 description "Peering LAN"
set interfaces ge-0/0/1 unit 0 family inet address 198.51.100.1/30
set interfaces lo0 unit 0 family inet address 192.168.255.2/32
set routing-options router-id 192.168.255.2
set routing-options autonomous-system 65001
set protocols ospf area 0.0.0.0 interface ge-0/0/0.0
set protocols ospf area 0.0.0.0 interface lo0.0 passive
set protocols bgp group CORE type internal
set protocols bgp group CORE local-address 192.168.255.2
set protocols bgp group CORE neighbor 192.168.255.1
"""

cfg_switch = """\
set system host-name access-sw-01
set system domain-name corp.example.com
set system time-zone UTC
set system services ssh root-login deny
set system ntp server 10.0.10.1
set interfaces ge-0/0/0 unit 0 family ethernet-switching interface-mode access
set interfaces ge-0/0/0 unit 0 family ethernet-switching vlan members vlan-100
set interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode access
set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members vlan-100
set interfaces ge-0/0/47 unit 0 family ethernet-switching interface-mode trunk
set interfaces ge-0/0/47 unit 0 family ethernet-switching vlan members all
set interfaces irb unit 100 family inet address 10.1.100.1/24
set vlans vlan-100 vlan-id 100
set vlans vlan-100 l3-interface irb.100
set protocols rstp interface ge-0/0/0 edge
set protocols rstp interface ge-0/0/1 edge
"""

configs = [
    {'hostname': 'core-router-01', 'date': '2026-05-30', 'note': 'daily backup',         'content': cfg_base},
    {'hostname': 'core-router-01', 'date': '2026-06-01', 'note': 'added ISP-B peering',  'content': cfg_updated},
    {'hostname': 'edge-router-02', 'date': '2026-06-01', 'note': 'initial backup',        'content': cfg_edge},
    {'hostname': 'access-sw-01',   'date': '2026-06-01', 'note': 'initial backup',        'content': cfg_switch},
]

for c in configs:
    dev_id = ids.get(c['hostname'])
    if not dev_id:
        print(f"  Skipping config for unknown device {c['hostname']}")
        continue
    r = requests.post(f'{BASE}/api/configs', json={
        'device_id': dev_id,
        'config_date': c['date'],
        'note': c['note'],
        'content': c['content'],
    })
    print(f"  Config [{c['hostname']} / {c['date']}]: {r.status_code}")

print("\nSeeding complete!")
