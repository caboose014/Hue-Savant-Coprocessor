#!/usr/bin/python
#     'http-Savant Bridge'
#     Copyright (C) '2018'  J14 Systems Ltd
#
#     This program is free software: you can redistribute it and/or modify
#     it under the terms of the GNU General Public License as published by
#     the Free Software Foundation, either version 3 of the License, or
#     (at your option) any later version.
#
#     This program is distributed in the hope that it will be useful,
#     but WITHOUT ANY WARRANTY; without even the implied warranty of
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#     GNU General Public License for more details.
#
#     You should have received a copy of the GNU General Public License
#     along with this program.  If not, see <http://www.gnu.org/licenses/>

import os
import time
import json
import copy
import math
import socket
import urllib3
import threading
import logging.handlers
from queue import Queue
from subprocess import call
from os.path import expanduser
from collections import namedtuple

try:
    import argparse
except ImportError:
    raise ImportError("Failed to import 'argparse'. Please install this module before continuing")

# Server version
server_version = '2.0'
# Represents a CIE 1931 XY coordinate pair.
xypoint = namedtuple('XYPoint', ['x', 'y'])

# LivingColors Iris, Bloom, Aura, LightStrips
gamuta = (
    xypoint(0.704, 0.296),
    xypoint(0.2151, 0.7106),
    xypoint(0.138, 0.08),
)

# hue a19 bulbs
gamutb = (
    xypoint(0.675, 0.322),
    xypoint(0.4091, 0.518),
    xypoint(0.167, 0.04),
)

# hue br30, a19 (gen 3), hue go, lightstrips plus
gamutc = (
    xypoint(0.692, 0.308),
    xypoint(0.17, 0.7),
    xypoint(0.153, 0.048),
)


class ColorHelper:
    def __init__(self, gamut=gamutb):
        self.red = gamut[0]
        self.lime = gamut[1]
        self.blue = gamut[2]

    @staticmethod
    def cross_product(p1, p2):
        return p1.x * p2.y - p1.y * p2.x

    def check_point_in_lamps_reach(self, p):
        v1 = xypoint(self.lime.x - self.red.x, self.lime.y - self.red.y)
        v2 = xypoint(self.blue.x - self.red.x, self.blue.y - self.red.y)
        q = xypoint(p.x - self.red.x, p.y - self.red.y)
        s = self.cross_product(q, v2) / self.cross_product(v1, v2)
        t = self.cross_product(v1, q) / self.cross_product(v1, v2)
        return (s >= 0.0) and (t >= 0.0) and (s + t <= 1.0)

    @staticmethod
    def get_closest_point_to_line(a, b, p):
        ap = xypoint(p.x - a.x, p.y - a.y)
        ab = xypoint(b.x - a.x, b.y - a.y)
        ab2 = ab.x * ab.x + ab.y * ab.y
        ap_ab = ap.x * ab.x + ap.y * ab.y
        t = ap_ab / ab2
        if t < 0.0:
            t = 0.0
        elif t > 1.0:
            t = 1.0
        return xypoint(a.x + ab.x * t, a.y + ab.y * t)

    def get_closest_point_to_point(self, xy_point):
        pab = self.get_closest_point_to_line(self.red, self.lime, xy_point)
        pac = self.get_closest_point_to_line(self.blue, self.red, xy_point)
        pbc = self.get_closest_point_to_line(self.lime, self.blue, xy_point)
        dab = self.get_distance_between_two_points(xy_point, pab)
        dac = self.get_distance_between_two_points(xy_point, pac)
        dbc = self.get_distance_between_two_points(xy_point, pbc)
        lowest = dab
        closest_point = pab
        if dac < lowest:
            lowest = dac
            closest_point = pac
        if dbc < lowest:
            closest_point = pbc
        cx = closest_point.x
        cy = closest_point.y
        return xypoint(cx, cy)

    @staticmethod
    def get_distance_between_two_points(one, two):
        dx = one.x - two.x
        dy = one.y - two.y
        return math.sqrt(dx * dx + dy * dy)

    def get_xy_point_from_rgb(self, red, green, blue):
        r = ((red + 0.055) / (1.0 + 0.055))**2.4 if (red > 0.04045) else (red / 12.92)
        g = ((green + 0.055) / (1.0 + 0.055))**2.4 if (green > 0.04045) else (green / 12.92)
        b = ((blue + 0.055) / (1.0 + 0.055))**2.4 if (blue > 0.04045) else (blue / 12.92)
        x = r * 0.664511 + g * 0.154324 + b * 0.162028
        y = r * 0.283881 + g * 0.668433 + b * 0.047685
        z = r * 0.000088 + g * 0.072310 + b * 0.986039
        cx = x / (x + y + z)
        cy = y / (x + y + z)
        xy_point = xypoint(cx, cy)
        in_reach = self.check_point_in_lamps_reach(xy_point)
        if not in_reach:
            xy_point = self.get_closest_point_to_point(xy_point)
        return xy_point

    def get_rgb_from_xy_and_brightness(self, x, y, bri=1):
        xy_point = xypoint(x, y)
        if not self.check_point_in_lamps_reach(xy_point):
            xy_point = self.get_closest_point_to_point(xy_point)
        y = bri
        x = (y / xy_point.y) * xy_point.x
        z = (y / xy_point.y) * (1 - xy_point.x - xy_point.y)
        r = x * 1.656492 - y * 0.354851 - z * 0.255038
        g = -x * 0.707196 + y * 1.655397 + z * 0.036152
        b = x * 0.051713 - y * 0.121364 + z * 1.011530
        r, g, b = map(
            lambda xx: (12.92 * xx) if (xx <= 0.0031308) else ((1.0 + 0.055) * pow(xx, (1.0 / 2.4)) - 0.055),
            [r, g, b]
        )
        r, g, b = map(lambda x2: max(0, x2), [r, g, b])
        max_component = max(r, g, b)
        if max_component > 1:
            r, g, b = map(lambda x4: x4 / max_component, [r, g, b])
        r, g, b = map(lambda x3: int(x3 * 255), [r, g, b])
        return r, g, b


class Converter:
    def __init__(self, gamut=gamutb):
        self.color = ColorHelper(gamut)

    def rgb_to_xy(self, red, green, blue):
        point = self.color.get_xy_point_from_rgb(red, green, blue)
        return point.x, point.y

    def xy_to_rgb(self, x, y, bri=1):
        r, g, b = self.color.get_rgb_from_xy_and_brightness(x, y, bri)
        return r, g, b


class CommunicationServer(threading.Thread):
    def __init__(self, message_queue, http_communications):
        threading.Thread.__init__(self)
        connection_loop = True
        self.running = True
        self.queue_test = False
        self.threads = []
        self.clients = []
        self.lock = threading.Lock()
        self.message_queue = message_queue
        self.httpcomms = http_communications
        while connection_loop:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_address = ('0.0.0.0', server_port)
            logger.info('#I7924 Starting up CommunicationServer on %s, port %s' % self.server_address)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.TCP_NODELAY, 1)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1048576)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1048576)
            try:
                logger.debug("#D5411 Binding to socket")
                self.sock.bind(self.server_address)
                logger.debug("#D9634 Binding successful, lets listen to what it says")
                self.sock.listen(1)
                connection_loop = False
            except socket.error as socketerror:
                logger.error("#E6535 We have a socket error. %s" % socketerror)
                time.sleep(10)
            except Exception as err_A:
                self.message_queue.put('shutdown')
                logger.error("#E7274 %s" % err_A, exc_info=True)
        logger.debug("#D8461 Savant communications server started successfully")

    def run(self):
        logger.debug("#D9621 setting up the message queue processor")
        queue_processor = threading.Thread(target=self.process_queue, args=())
        queue_processor.setDaemon(True)
        logger.debug("#D5417 Starting the message queue processor")
        queue_processor.start()
        logger.debug("#D8644 Message queue processor started, adding a record of thread to threads array")
        self.lock.acquire()
        self.threads.append(queue_processor)
        self.lock.release()
        logger.debug("#D7604 Starting the HTTP communications server")
        self.httpcomms.start()
        logger.debug("#D6547 Setting up queue watcher")
        watcher = threading.Thread(target=self.queue_watcher, args=())
        watcher.setDaemon(True)
        watcher.start()
        while self.running:
            logger.debug("#D2395 Setting up a Savant connection listener")
            listen_process = threading.Thread(target=self.listen_messages, args=(self.sock.accept()))
            listen_process.setDaemon(True)
            logger.debug("#D6125 Starting the Savant connection listener")
            listen_process.start()
            logger.debug("#D9793 Adding connection listener to threads array")
            self.lock.acquire()
            self.threads.append(listen_process)
            self.lock.release()
        logger.info("#I0472 Closing CommunicationsServer")
        self.sock.close()

    def queue_watcher(self):
        global server_running
        while True:
            self.message_queue.put("queue_test")
            time.sleep(5)
            if self.queue_test:
                logger.debug("#D5831 Message queue responded and should be working")
                self.queue_test = False
            else:
                server_running = False
                logger.warning("W5297 Server needs to be restarted, Message Queue has stopped responding")
            time.sleep(300)

    def process_queue(self):
        global server_running
        logger.debug("#D4268 Message queue processor started")
        while True:
            try:
                message = self.message_queue.get()
                logger.debug("#D8480 Message received: %s" % message)
                if message == 'shutdown':
                    logger.debug("#D2738 Message 'Shutdown' received. Closing communications servers.")
                    self.running = False
                    logger.debug("#D1842 Force a new connection to break connection listener")
                    sock2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock2.connect(self.server_address)
                    time.sleep(1)
                    break
                if message == 'restart':
                    logger.debug("#D2492 Restart requested from message queue")
                    server_running = False
                elif message == 'queue_test':
                    if verbose:
                        logger.debug("#D8296 Responding to queue test with true")
                    self.queue_test = True
                else:
                    for client in self.clients:
                        try:
                            logger.debug("#D2710 Sending received message to client")
                            client.send((message + '\r\n').encode())
                            time.sleep(0.1)
                        except TypeError:
                            logger.debug("#D6116 Message format not right as string, formatting for JSON. "
                                         "Sending to client")
                            client.send((json.dumps(str(message)) + '\r\n').encode())
                            time.sleep(0.1)
                        except Exception as err_C:
                            logger.error("E1868 Message format issue: %s" % err_C)
            except Exception as err_B:
                logger.error("#E5461 Message Queue had a problem processing a message: %s" % err_B, exc_info=True)
                call(["service", "hue-coprocessor", "restart"])
        self.lock.acquire()
        logger.debug("#D9720 Removing message processor from threads array")
        self.threads.remove(threading.currentThread())
        self.lock.release()
        logger.debug("#D5465 Finishing message processor thread")

    def listen_messages(self, connection, client_address):
        try:
            logger.info('#E8007 %s connected.' % client_address[0])
            self.lock.acquire()
            logger.debug("#E4220 Adding new client %s to threads array" % client_address[0])
            self.clients.append(connection)
            self.lock.release()
            logger.debug("#D5767 Sending welcome message to client %s" % client_address[0])
            connection.send(('#' + 'J14 HTTP-Savant Relay v%s\r\n' % server_version).encode())
            time.sleep(2)
            logger.debug("#D8619 Pushing all device states to client %s" % client_address[0])
            self.httpcomms.new_connect(connection)
            while True:
                datarecv = connection.recv(1024)
                logger.debug("#D4893 Received data from %s" % client_address[0])
                if not datarecv:
                    logger.debug("#D0308 Invalid data received from %s. Closing client connection" % client_address[0])
                    break
                datarecv = datarecv.replace('\n', '')
                datarecv = datarecv.replace('\r', '')
                data = datarecv
                if data.encode('hex') == 'fffb06':
                    logger.debug("#D3612 Received ^C from client %s. Closing client connection" % client_address[0])
                    connection.close()
                    break
                if data == 'close' or data == 'exit' or data == 'quit':
                    logger.debug("#D1259 Received close, exit, or quit string from client %s. "
                                 "Closing client connection" % client_address[0])
                    break
                if data == 'restart':
                    logger.debug("#D6629 Received restart string from client %s. "
                                 "Requesting server restart" % client_address[0])
                    self.message_queue.put('restart')
                    break
                elif data == '':
                    logger.debug("#D3713 Received empty data string from client %s" % client_address[0])
                    connection.send("#32" + 'Empty Command String\r\n')
                else:
                    try:
                        logger.debug("#D5443 Received command from client: %s" % client_address[0])
                        command = data
                        split_data = command.split('%')
                        try:
                            command = split_data[0]
                            body = split_data[1]
                            if len(split_data) == 3:
                                return_data = self.httpcomms.send_command(cmd_type='put', command=command,
                                                                          body_content=json.loads(body),
                                                                          xy=split_data[2])
                            else:
                                return_data = self.httpcomms.send_command(cmd_type='put', command=command,
                                                                          body_content=json.loads(body))
                            try:
                                for update in json.loads(return_data):
                                    if 'success' in update:
                                        for key in update['success']:
                                            keys = key.strip("/").split("/")
                                            if update['success'][key] == "0":
                                                mydata = {keys[2]: {keys[3]: update['success'][key]}}
                                                if keys[3] == "on" and not bool(update['success'][key]):
                                                    mydata[keys[2]]["bri"] = "0"
                                                connection.send(('#' + json.dumps(
                                                    {keys[0].rstrip('s'): {"id": keys[1], "info": mydata}}) + '\r\n').encode())
                                            else:
                                                connection.send(('#' + json.dumps(update) + '\r\n').encode())
                                    else:
                                        connection.send(('#' + json.dumps(update) + '\r\n').encode())
                            except TypeError:
                                connection.send('#' + json.dumps(return_data) + '\r\n')

                        except IndexError:
                            return_data = self.httpcomms.send_command(cmd_type='get', command=command)
                            for item in return_data:
                                if command == "lights":
                                    if not return_data[item]['state']['on']:
                                        return_data[item]['state']['bri'] = 0
                                        return_data[item]['state']['hue'] = 0
                                        return_data[item]['state']['sat'] = 0

                                    # print(return_data)

                                    return_me = return_data[item]
                                elif command == "groups":
                                    if not return_data[item]["type"] in devicetypes:
                                        continue
                                    if not return_data[item]['action']['on']:
                                        return_data[item]['action']['bri'] = 0
                                        return_data[item]['action']['hue'] = 0
                                        return_data[item]['action']['sat'] = 0
                                    return_me = return_data[item]
                                elif command == "scenes":
                                    if len(return_data[item]["appdata"]) < 0:
                                        continue
                                    return_me = {"name": return_data[item]["name"],
                                                 "lights": ', '.join(return_data[item]["lights"])}
                                elif command == "sensors":
                                    if not return_data[item]["modelid"] in devicetypes:
                                        continue
                                    return_me = return_data[item]
                                else:
                                    return_me = return_data[item]
                                connection.send(('#' + json.dumps(
                                    {command.rstrip("s"): {"id": item, "info": return_me}}) + '\r\n').encode())
                        except TypeError:
                            logger.debug("#D6939 TypeError, could not process received data from client %s"
                                         % client_address[0])
                            connection.send('#E0658 TypeError, could not process received data\r\n')

                    except ValueError:
                        logger.debug("#D2057 ValueError, could not process received data from client %s"
                                     % client_address[0])
                        connection.send('#E7804 ValueError, could not process received data\r\n')
                    except TypeError:
                        logger.debug("#D9011 TypeError, could not process received data from client %s"
                                     % client_address[0])
                        connection.send('#E7223 TypeError, could not process received data\r\n')
                    except Exception as err_D:
                        logger.error("#E3017 %s" % err_D, exc_info=True)
                        connection.send('#E8408 %s\r\n' % err_D)

            logger.debug("#D4024 Client %s thread closing" % client_address[0])
            self.lock.acquire()
            logger.debug("#D4694 Removing client %s from clients array, and thread from threads array"
                         % client_address[0])
            self.clients.remove(connection)
            self.threads.remove(threading.currentThread())
            self.lock.release()
            connection.close()
            logger.info('#I7373 %s disconnected.' % client_address[0])
        except Exception as err_E:
            logger.error("#E0910 %s" % err_E, exc_info=True)


class HTTPBridge(threading.Thread):
    def __init__(self, savant_queue):
        threading.Thread.__init__(self)
        self.message_queue = savant_queue
        self.lock = threading.Lock()
        self.threads = []
        self.converter = Converter(gamutc)
        self.store = {"lights": {}, "groups": {}, "sensors": {}, "scenes": {}, "all": {}}
        logger.debug("#D0930 HTTPBridge started")

    def run(self):
        logger.debug("#D1124 Setting up device poller")
        poller = threading.Thread(target=self.http_poller, args=())
        poller.setDaemon(True)
        poller.start()
        logger.debug("#D6387 Adding device poller thread to threads array")
        self.lock.acquire()
        self.threads.append(poller)
        self.lock.release()
        logger.debug("#D0868 Setting up poller watcher")
        watcher = threading.Thread(target=self.thread_watcher, args=())
        watcher.setDaemon(True)
        watcher.start()

    def thread_watcher(self):
        while True:
            for thread in self.threads:
                if not thread.is_alive():
                    logger.error("#E2052 HTTP Poller is not alive!!")
                    self.threads.remove(thread)
                    logger.debug("#D0202 Setting up device poller")
                    poller = threading.Thread(target=self.http_poller, args=())
                    poller.setDaemon(True)
                    poller.start()
                    logger.debug("#D2399 Adding device poller thread to threads array")
                    self.lock.acquire()
                    self.threads.append(poller)
                    self.lock.release()
            time.sleep(30)

    def http_poller(self):
        logger.debug("#D2549 Device poller started")
        logger.debug("#D0890 Poller PID: %s" % threading.currentThread().ident)
        while True:
            try:
                if verbose:
                    logger.debug("#D4899 Asking for device statuses from %s" % http_ip_address)
                result = self.send_command()
                if verbose:
                    logger.debug("#D2547 Received update successfully. Processing data...")
                removekeys = ['config', 'resourcelinks', 'rules', 'schedules']
                for removekey in removekeys:
                    try:
                        del result[removekey]
                    except KeyError:
                        pass

                if not self.store['all'] == result:
                    logger.debug("#D8176 HTTP Data chanced since last poll")
                    self.store["all"] = copy.deepcopy(result)
                    #
                    # Lights
                    #
                    for light_id in result.get('lights'):
                        light_data = result.get('lights').get(light_id)

                        if light_id not in self.store["lights"]:
                            logger.debug("#D0139 Found a new LightID '%s', adding it to monitored lights" % light_id)
                            self.store["lights"][light_id] = copy.deepcopy(light_data)
                        try:
                            if not self.store["lights"][light_id] == light_data:
                                logger.debug("#D2000 Light '%s' information has changed"
                                             % light_id)
                                self.store["lights"][light_id] = copy.deepcopy(light_data)
                                logger.debug("#D1820 Notifying all clients of level change for light '%s'"
                                             % light_id)
                                if not light_data['state']['on']:
                                    light_data['state']['bri'] = 0
                                    light_data['state']['hue'] = 0
                                    light_data['state']['sat'] = 0
                                for key in remove_keys:
                                    try:
                                        light_data.pop(key, None)
                                    except KeyError:
                                        pass
                                    except IndexError:
                                        pass
                                self.message_queue.put('#' + json.dumps(
                                    {"light": {"id": light_id, "info": light_data}}))
                                if 'xy' in light_data['state']:
                                    pntx, pnty = light_data['state']['xy']
                                    red, green, blue = self.converter.xy_to_rgb(pntx, pnty)

                                    self.message_queue.put('#' + json.dumps(
                                        {"light_rgb": {"id": light_id, "info": [
                                            {"color": "r", "value": red},
                                            {"color": "g", "value": green},
                                            {"color": "b", "value": blue}
                                        ]}}
                                    ))
                        except Exception as err_F:
                            logger.error("#E6663 %s" % err_F, exc_info=True)
                    #
                    # Groups
                    #
                    for group_id in result.get('groups'):
                        if result.get("groups").get(group_id).get("type") in devicetypes:
                            group_data = result.get('groups').get(group_id)
                            if group_id not in self.store["groups"]:
                                logger.debug("#D2418 Found a new GroupID '%s', adding it to monitored groups"
                                             % group_id)
                                self.store["groups"][group_id] = copy.deepcopy(group_data)
                            try:
                                if not self.store["groups"][group_id] == group_data:
                                    logger.debug("#D9999 Group '%s' information has changed"
                                                 % group_id)
                                    self.store["groups"][group_id] = copy.deepcopy(group_data)
                                    logger.debug("#D0908 Notifying all clients of level change for group '%s'"
                                                 % group_id)
                                    if not group_data['action']['on']:
                                        group_data['action']['bri'] = 0
                                        group_data['action']['hue'] = 0
                                        group_data['action']['sat'] = 0
                                    self.message_queue.put('#' + json.dumps(
                                        {"group": {"id": group_id, "info": group_data}}))
                                    if 'xy' in group_data['action']:
                                        pntx, pnty = group_data['action']['xy']
                                        red, green, blue = self.converter.xy_to_rgb(pntx, pnty)

                                        self.message_queue.put('#' + json.dumps(
                                            {"group_rgb": {"id": group_id, "info": [
                                                {"color": "r", "value": red},
                                                {"color": "g", "value": green},
                                                {"color": "b", "value": blue}
                                            ]}}
                                        ))
                            except Exception as err_G:
                                logger.error("#E7134 %s" % err_G, exc_info=True)
                    #
                    # Sensors
                    #
                    for sensor_id in result.get('sensors'):
                        if result.get("sensors").get(sensor_id).get("modelid") in devicetypes:
                            sensor_data = result.get('sensors').get(sensor_id)
                            if sensor_id not in self.store["sensors"]:
                                logger.debug("#D0278 Found a new SensorID '%s', adding it to monitored "
                                             "sensors" % sensor_id)
                                self.store["sensors"][sensor_id] = copy.deepcopy(sensor_data)
                            try:
                                if not self.store["sensors"][sensor_id] == sensor_data:
                                    logger.debug("#D1170 Sensor '%s' information has changed"
                                                 % sensor_id)
                                    self.store["sensors"][sensor_id] = copy.deepcopy(sensor_data)
                                    logger.debug("#D4421 Notifying all clients of level change for sensor '%s'"
                                                 % sensor_id)
                                    for key in remove_keys:
                                        try:
                                            sensor_data.pop(key, None)
                                        except KeyError:
                                            pass
                                        except IndexError:
                                            pass
                                    self.message_queue.put('#' + json.dumps({
                                        "sensor": {"id": sensor_id, "info": sensor_data}}))
                            except Exception as err_H:
                                logger.error("#E3942 %s" % err_H, exc_info=True)

            except Exception as err_I:
                logger.error("#E9155 %s" % err_I, exc_info=True)
            if verbose:
                logger.debug("#D5604 Finished poll. Waiting for next poll.")
            time.sleep(http_poll_interval)

    def send_command(self, cmd_type='get', command='', body_content=None, xy=None):
        result = ''
        if body_content is None:
            body_content = {}
        try:
            if cmd_type == 'get':
                if command:
                    try:
                        result = json.loads(http_req.request('GET', 'http://%s/api/%s/%s' % (http_ip_address, http_key,
                                                                                             command), timeout=4).data)
                        if verbose:
                            logger.debug("#D9455 Sent command (%s) to controller" % command)
                    except urllib3.exceptions.HTTPError:
                        logger.error("#E1823 Command ('%s') HTTP Error" % command)
                    except TypeError:
                        logger.error("#E6378 Command ('%s') JSON Type Error" % command)
                    except Exception as err_J:
                        logger.error("#E0301 Command ('%s') Caught an error: %s" %
                                     (command, err_J), exc_info=True)
                else:
                    try:
                        result = json.loads(http_req.request('GET', "http://%s/api/%s" % (http_ip_address, http_key),
                                                             timeout=4).data)
                        if verbose:
                            logger.debug("#D5451 Command ('State Poll') sent successfully")
                    except urllib3.exceptions.HTTPError:
                        logger.error("#E9087 Command ('State Poll') HTTP Error")
                    except TypeError:
                        logger.error("#E8721 Command ('State Poll') JSON Type Error")
                    except Exception as err_K:
                        logger.error("#E9031 Command (State Poll') Caught an error: %s" %
                                     err_K, exc_info=True)
            elif cmd_type == 'put':
                if xy:
                    part_a = command.split('/')
                    if part_a[0] == 'lights':
                        pntx, pnty = self.store[part_a[0]][part_a[1]]['state']['xy']
                    else:
                        pntx, pnty = self.store[part_a[0]][part_a[1]]['action']['xy']
                    cur_r, cur_g, cur_b = self.converter.xy_to_rgb(pntx, pnty)
                    if xy == "r":
                        pntxx, pntyy = self.converter.rgb_to_xy(body_content['bri'], cur_g, cur_b)
                    elif xy == "g":
                        pntxx, pntyy = self.converter.rgb_to_xy(cur_r, body_content['bri'], cur_b)
                    else:
                        # xy == "b" - assumed
                        pntxx, pntyy = self.converter.rgb_to_xy(cur_r, cur_g, body_content['bri'])
                    body_content = {'on': True, 'xy': [pntxx, pntyy]}
                elif "bri" in body_content:
                    if "transitiontime" in body_content and isinstance(body_content['transitiontime'], float):
                        body_content['transitiontime'] = int(math.ceil(body_content['transitiontime']))
                    if body_content['bri'] < 1:
                        body_content['on'] = False
                        body_content.pop('bri', None)
                try:
                    result = json.loads(http_req.request('PUT', "http://%s/api/%s/%s" %
                                                         (http_ip_address, http_key, command),
                                                         body=json.dumps(body_content), timeout=4).data)
                    if verbose:
                        logger.debug("#D7207 Sent command (%s - %s) to controller" % (command,
                                                                                      json.dumps(body_content)))
                except urllib3.exceptions.HTTPError:
                    logger.error("#E5411 Command ('%s') HTTP Error" % command)
                except ValueError:
                    logger.error("#E0786 Command ('%s') JSON Value Error" % command)
                except TypeError:
                    logger.error("#E8080 Command ('%s') JSON Type Error" % command)
                except Exception as err_L:
                    logger.error("#E4663 Command ('%s') Caught an error: %s" %
                                 (command, err_L), exc_info=True)
            else:
                if command:
                    try:
                        result = json.loads(http_req.request('POST', "http://%s/api/%s/%s" %
                                                             (http_ip_address, http_key, command),
                                                             body=json.dumps(body_content), timeout=4).data)
                        if verbose:
                            logger.debug("#D7492 Sent command (%s - %s) to controller" % (command,
                                                                                          json.dumps(body_content)))
                    except urllib3.exceptions.HTTPError:
                        logger.error("#E6456 Command ('%s') HTTP Error" % command)
                    except ValueError:
                        logger.error("#E5525 Command ('%s') JSON Value Error" % command)
                    except TypeError:
                        logger.error("#E2833 Command ('%s') JSON Type Error" % command)
                    except Exception as err_M:
                        logger.error("#E2030 Command ('%s') Caught an error: %s" %
                                     (command, err_M), exc_info=True)
                    if verbose:
                        logger.debug("#D1701 Command ('%s') sent successfully" % command)
                else:
                    try:
                        result = json.loads(http_req.request('GET', "http://%s/api/%s" % (http_ip_address, http_key),
                                                             body=json.dumps(body_content), timeout=4).data)
                        if verbose:
                            logger.debug("#D3329 Command ('State Poll') sent successfully")
                    except urllib3.exceptions.HTTPError:
                        logger.error("#E7751 Command ('State Poll') HTTP Error")
                    except ValueError:
                        logger.error("#E4494 Command ('State Poll') JSON Value Error")
                    except TypeError:
                        logger.error("#E9679 Command ('State Poll') JSON Type Error")
                    except Exception as err_N:
                        logger.error("#E7958 Command ('State Poll') Caught an error: %s" % err_N, exc_info=True)
            return result
        except Exception as err_O:
            logger.error("#E4933 Error sending Command. HTTP Request failed. %s" % err_O, exc_info=True)
            self.message_queue.put('#' + "Invalid HTTP command")

    def new_connect(self, connection):
        logger.debug("#E1154 New client connected. Sending all device states")
        #
        # Lights
        #
        try:
            for light_id in self.store['lights']:
                light_data = self.store['lights'][light_id]
                if not light_data['state']['on']:
                    light_data['state']['bri'] = 0
                    light_data['state']['hue'] = 0
                    light_data['state']['sat'] = 0
                for key in remove_keys:
                    try:
                        light_data.pop(key, None)
                    except KeyError:
                        pass
                    except IndexError:
                        pass
                connection.send(('#' + json.dumps({"light": {"id": light_id, "info": light_data}}) + '\r\n').encode())
                if 'xy' in light_data['state']:
                    pntx, pnty = light_data['state']['xy']
                    red, green, blue = self.converter.xy_to_rgb(pntx, pnty)

                    self.message_queue.put('#' + json.dumps(
                        {"light_rgb": {"id": light_id, "info": [
                            {"color": "r", "value": red},
                            {"color": "g", "value": green},
                            {"color": "b", "value": blue}
                        ]}}
                    ))
        except KeyError:
            logger.error('#E4092 No Light info to send')
        except socket.error as err_Z:
            logger.error("#E6782 socket.error: %s" % err_Z, exc_info=True)
            # Finish the function as nothing more will work
            return None
        except Exception as err_Z:
            logger.error("#E9683 Sending Lights to client caught an error: %s" % err_Z, exc_info=True)
        #
        # Groups
        #
        try:
            for group_id in self.store['groups']:
                group_data = self.store['groups'][group_id]
                if not group_data['action']['on']:
                    group_data['action']['bri'] = 0
                    group_data['action']['hue'] = 0
                    group_data['action']['sat'] = 0
                connection.send(('#' + json.dumps({"group": {"id": group_id, "info": group_data}}) + '\r\n').encode())
                # self.message_queue.put('#' + json.dumps({"group": {"id": group_id, "info": group_data}}))
                if 'xy' in group_data['action']:
                    pntx, pnty = group_data['action']['xy']
                    red, green, blue = self.converter.xy_to_rgb(pntx, pnty)

                    self.message_queue.put('#' + json.dumps(
                        {"group_rgb": {"id": group_id, "info": [
                            {"color": "r", "value": red},
                            {"color": "g", "value": green},
                            {"color": "b", "value": blue}
                        ]}}
                    ))
        except KeyError:
            logger.error('#E1435 No Group info to send')
        except socket.error as err_P:
            logger.error("#E8313 socket.error: %s" % err_P, exc_info=True)
            # Finish the function as nothing more will work
            return None
        except Exception as err_Q:
            logger.error("#E7062 Sending Group to client caught an error: %s" % err_Q, exc_info=True)
        #
        # Sensors
        #
        try:
            for sensor_id in self.store['sensors']:
                sensor_data = self.store['sensors'][sensor_id]
                for key in remove_keys:
                    try:
                        # print(self.store['sensors'])
                        # print(sensor_id)
                        # print(key)
                        del self.store['sensors'][sensor_id][key]
                        # sensor_id.pop(key, None)
                    except KeyError:
                        pass
                    except IndexError:
                        pass
                connection.send(('#' + json.dumps({"sensor": {"id": sensor_id, "info": sensor_data}}) + '\r\n').encode())
                # self.message_queue.put('#' + json.dumps({"sensor": {"id": sensor_id, "info": sensor_data}}))
        except KeyError:
            logger.error('#E6132 No Sensor info to send')
        except socket.error as err_R:
            logger.error("#E8114 socket.error: %s" % err_R, exc_info=True)
            # Finish the function as nothing more will work
            return None
        except Exception as err_S:
            logger.error("#E2635 Sending Sensors to client caught an error: %s" % err_S, exc_info=True)
        #
        # Scenes
        #
        try:
            for scene_id in self.store['all']['scenes']:
                scene_data = self.store['all']['scenes'][scene_id]
                if len(scene_data["appdata"]) > 0:
                    connection.send(('#' + json.dumps({"scene": {"id": scene_id, "info": {
                        "name": scene_data["name"], "lights": ', '.join(scene_data["lights"])}}}) + '\r\n').encode())
                    # self.message_queue.put('#' + json.dumps({"scene": {"id": scene_id, "info": {
                    #    "name": scene_data["name"], "lights": ', '.join(scene_data["lights"])}}}))
        except KeyError:
            logger.error('#E0652 No Scene info to send')
        except socket.error as err_T:
            logger.error("#E3559 socket.error: %s" % err_T, exc_info=True)
            # Finish the function as nothing more will work
            return None
        except Exception as err_U:
            logger.error("#E4272 Sending Scenes to client caught an error: %s" % err_U, exc_info=True)

        logger.debug("#D3476 Finished sending information to client")


class SingleLevelFilter(logging.Filter):
    def __init__(self, passlevel, reject):
        logging.Filter.__init__(self)
        self.passlevel = passlevel
        self.reject = reject

    def filter(self, record):
        if self.reject:
            return record.levelno != self.passlevel
        else:
            return record.levelno == self.passlevel


def run():
    global server_running
    queue = Queue(maxsize=100)
    try:
        logger.debug("#D3571 Starting the HTTP communications thread")
        httpcomms = HTTPBridge(queue)
        logger.debug("#D9699 Starting the Savant communications thread")
        CommunicationServer(queue, httpcomms).start()
        while server_running:
            time.sleep(5)
        queue.put('shutdown')
        logger.info('#I3608 Restart request detected, restarting server')
    except KeyboardInterrupt:
        queue.put('shutdown')
        logger.info('#I8417 KeyboardInterrupt detected, shutting down server')
        raise SystemExit
    except Exception as err_V:
        queue.put('shutdown')
        logger.error("#E3002 %s" % err_V, exc_info=True)
    finally:
        logger.debug("#D7856 Hit end of 'run()' function")
        queue.put('shutdown')


def discover_http():
    try:
        result = json.loads(http_req.request('GET', 'https://discovery.meethue.com').data)[0]
        return result['internalipaddress']
    except Exception as err_Y:
        logger.error("E6845 %s" % err_Y, exc_info=True)
        return False


def register_api_key(ip_address):
    while True:
        try:
            logger.debug("#D1605 Obtaining API key from: %s" % ip_address)
            result = json.loads(http_req.request('POST', 'http://%s/api' % ip_address,
                                                 body=json.dumps({"devicetype": "HTTPBridge"}), timeout=4).data)[0]
            if 'error' in result:
                logger.error(json.dumps({"E7489 error": {"description": result["error"]["description"]}}))
                time.sleep(10)
            else:
                logger.debug("D6282 API key successfully created: %s" % result["success"]["username"])
                return result["success"]["username"]
        except Exception as err_W:

            logger.error("E9800 %s" % err_W, exc_info=True)
            return False


def load_settings(ip_address, key, cur_settings=None):
    if cur_settings is None:
        cur_settings = {}
    global http_key
    global http_ip_address
    logger.debug('#D1196 Loading settings')
    if ip_address == "":
        try:
            http_ip_address = cur_settings['internalipaddress']
            if http_ip_address:
                logger.debug('#D6950 IP address set to %s from settings file' % http_ip_address)
            else:
                http_ip_address = discover_http()
                logger.debug('#D0927 IP address set to %s from discovery' % http_ip_address)
                if not http_ip_address:
                    logger.error('#E3843 Unable to find HTTP IP address, shutting down')
                    raise SystemExit

        except KeyError:
            http_ip_address = discover_http()
            logger.debug('#D8058 IP address set to %s from discovery' % http_ip_address)
            if not http_ip_address:
                logger.error('#E2151 Unable to find HTTP IP address, shutting down')
                raise SystemExit

    if key == "":
        try:
            http_key = cur_settings['key']
            if http_key:
                logger.debug('#D0710 API Key set to %s from settings file' % http_key)
            else:
                http_key = register_api_key(http_ip_address)
                logger.debug('#D7164 API Key set to %s from register' % http_key)
                if not http_key:
                    logger.error('#E3612 Unable to set API key, shutting down')
                    raise SystemExit
        except KeyError:
            http_key = register_api_key(http_ip_address)
            logger.debug('#D2725 API Key set to %s from register' % http_key)
            if not http_key:
                logger.error('#E3223 Unable to set API key, shutting down')
                raise SystemExit

    settings_data = {"key": http_key, "internalipaddress": http_ip_address}
    with open(settings_file, 'w') as set_file:
        json.dump(settings_data, set_file)


if __name__ == '__main__':
    home = expanduser("~")
    # Argument parser and options
    parser = argparse.ArgumentParser(description="J14 HTTP-Savant Relay Server")
    parser.add_argument('-l', '--log', help="Logging Level: CRITICAL, ERROR, WARNING, INFO, DEBUG, NOTSET",
                        required=False, default="INFO")
    parser.add_argument('-d', '--debug', help="Set Logging Level to DEBUG",
                        required=False, action='store_true')
    parser.add_argument('-v', '--verbose', help="Set DEBUG logging to VERBOSE",
                        required=False, action='store_true')
    parser.add_argument('-f', '--file', help="Logging File path",
                        required=False, default="%s/http-savant.log" % home)
    parser.add_argument('-P', '--port', help="Port to start the telnet server on (for Savant communication)",
                        required=False, default=8085)
    parser.add_argument('-k', '--key', help="HTTP API Key",
                        required=False, default="")
    parser.add_argument('-a', '--address', help="HTTP API IP address",
                        required=False, default="")
    parser.add_argument('-i', '--interval', help="HTTP API device status polling interval (in seconds)",
                        required=False, default=1.0)
    parser.add_argument('-m', '--maxrecon', help="Maximum number of restarts after script crash",
                        required=False, default=100)
    parser.add_argument('-r', '--recontime', help="First reconnect delay",
                        required=False, default=2)
    parser.add_argument('-t', '--type', help="Add multiple arguments to increase the sensor, "
                                             "and group types we are looking for",
                        required=False, action='append', type=str)
    args = parser.parse_args()
    log_exists = os.path.isfile(args.file)
    verbose = False
    # Setup the logging engine
    if not args.debug:
        numeric_level = getattr(logging, args.log.upper(), None)
        if not isinstance(numeric_level, int):
            raise ValueError('Invalid log level: %s' % args.log)
    else:
        numeric_level = 10
        if args.verbose:
            verbose = True

    logger = logging.getLogger("savant_coprocessor")
    logformat = logging.Formatter('%(asctime)s - %(levelname)s: %(message)s')
    log_rotate = logging.handlers.RotatingFileHandler(args.file, maxBytes=10*1024*1024, backupCount=5)
    logger.setLevel(numeric_level)
    log_rotate.setFormatter(logformat)
    logger.addHandler(log_rotate)

    # Set up some global variables
    server_port = args.port
    http_ip_address = args.address
    http_key = args.key
    http_poll_interval = float(args.interval)
    max_reconnects = args.maxrecon
    reconnect_delay = args.recontime
    devicetypes = ['SML001', 'Room']
    remove_keys = [
        'swupdate',
        'swversion',
        'uniqueid',
        'capabilities',
        'colorgamut',
        'config',
        'productname',
        'manufacturername'
    ]
    settings_file = "%s/savant-hue.json" % home
    http_req = urllib3.PoolManager()

    # Start fresh log file
    if log_exists:
        # logger.handlers[0].doRollover()
        log_rotate.doRollover()

    logger.debug("#D6575 Relay started")

    # Create an array of device types to monitor
    if args.type:
        for watchtype in args.type:
            logger.debug("#D8620 Adding device type '%s' to monitor" % watchtype)
            devicetypes.append(watchtype)

    # Load settings
    if http_key == "" or http_ip_address == "":
        try:
            with open(settings_file, 'r') as fp:
                file_settings = json.load(fp)
            load_settings(http_ip_address, http_key, file_settings)
        except IOError:
            logger.error("#E2961 No Settings File, creating new file and adding settings")
            new_settings_data = {"key": "", "internalipaddress": ""}
            with open(settings_file, 'w') as fp:
                json.dump(new_settings_data, fp)
            load_settings(http_ip_address, http_key)
            file_settings = {"internalipaddress": http_ip_address, "key": http_key}
            with open(settings_file, 'w') as fp:
                json.dump(file_settings, fp)

    # Spit out some debug information to start with
    logger.debug("#D0328 Logging level = %s" % args.log)
    logger.debug("#D7044 Logfile = %s" % args.file)
    logger.debug("#D5563 Server Port = %s" % args.port)
    logger.debug("#D3559 HTTP key = %s" % http_key)
    logger.debug("#D6628 HTTP IP address = %s" % http_ip_address)
    logger.debug("#D4278 HTTP polling interval = %s" % args.interval)

    while True:
        logger.debug("#D9328 Starting main loop")
        if max_reconnects > 1:
            try:
                logger.debug("#D2801 Starting 'run()' function")
                server_running = True
                run()
            except socket.error as err:
                logger.error('#E2114 Connect error: %s' % err, exc_info=True)
                reconnect_delay *= 2
            logger.info('#I1704 Waiting', reconnect_delay, 'seconds before restart.')
            logger.info('#I6382 Will try', max_reconnects, 'more times before shutdown')
            max_reconnects -= 1
            time.sleep(reconnect_delay)
            logger.info('#I6266 Restarting...')
        else:
            logger.debug("#D5312 End of script, exiting")
            logger.info('#I2894 EOL, goodbye')
            raise SystemExit
