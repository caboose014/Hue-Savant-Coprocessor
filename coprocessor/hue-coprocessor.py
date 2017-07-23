#!/usr/bin/python
#     
#     'http-Savant Bridge'
#     Copyright (C) '2017'  J14 Systems Ltd
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

import time
import json
import copy
import socket
import urllib2
import logging
import threading
from Queue import Queue
from os.path import expanduser

try:
    import argparse
except ImportError:
    raise ImportError("Failed to import 'argparse'. Please install this module before continuing")

# Server version
server_version = '1.0'


class CommunicationServer(threading.Thread):
    # Logging section 12000
    def __init__(self, message_queue, http_communications):
        threading.Thread.__init__(self)
        connection_loop = True
        self.running = True
        self.threads = []
        self.clients = []
        self.lock = threading.Lock()
        self.message_queue = message_queue
        self.httpcomms = http_communications
        while connection_loop:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_address = ('0.0.0.0', server_port)
            logging.info('#I12001 Starting up CommunicationServer on %s, port %s' % self.server_address)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.TCP_NODELAY, 1)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1048576)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1048576)
            try:
                logging.debug("#D12001 Binding to socket")
                self.sock.bind(self.server_address)
                logging.debug("#D12002 Binding successful, lets listen to what it says")
                self.sock.listen(1)
                connection_loop = False
            except socket.error, socket_error:
                logging.error("#E12001 We have a socket error. %s" % socket_error)
                time.sleep(10)
            except Exception as err1:
                self.message_queue.put('shutdown')
                logging.error("#I12002 %s" % err1.message)
        logging.debug("#D12003 Savant communications server started successfully")

    def run(self):
        # Logging section 11000
        logging.debug("#D11001 setting up the message queue processor")
        queue_processor = threading.Thread(target=self.process_queue, args=())
        queue_processor.setDaemon(True)
        logging.debug("#D11002 Starting the message queue processor")
        queue_processor.start()
        logging.debug("#D11003 Message queue processor started, adding a record of thread to threads array")
        self.lock.acquire()
        self.threads.append(queue_processor)
        self.lock.release()
        logging.debug("#D11004 Starting the HTTP communications server")
        self.httpcomms.start()
        while self.running:
            logging.debug("#D11005 Setting up a Savant connection listener")
            listen_process = threading.Thread(target=self.listen_messages, args=(self.sock.accept()))
            listen_process.setDaemon(True)
            logging.debug("#D11006 Starting the Savant connection listener")
            listen_process.start()
            logging.debug("#D11007 Adding connection listener to threads array")
            self.lock.acquire()
            self.threads.append(listen_process)
            self.lock.release()

        logging.info("#I11001 Closing CommunicationsServer")
        self.sock.close()

    def process_queue(self):
        # Logging section 10000
        logging.debug("#D10001 Message queue processor started")
        while True:
            message = self.message_queue.get()
            logging.debug("#D10002 Message received: %s" % message)
            if message == 'shutdown':
                logging.debug("#D10003Message 'Shutdown' received. Closing communications servers.")
                self.running = False
                logging.debug("#D10004 Force a new connection to break connection listener")
                sock2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock2.connect(self.server_address)
                time.sleep(1)
                break
            else:
                for client in self.clients:
                    try:
                        logging.debug("#D10005 Sending received message to client")
                        client.send(message + "\r\n")
                    except TypeError:
                        logging.debug("#D10006 Message format not right as string, formatting for JSON. "
                                      "Sending to client")
                        client.send(json.dumps(str(message)) + "\r\n")
        self.lock.acquire()
        logging.debug("#D10007 Removing message processor from threads array")
        self.threads.remove(threading.currentThread())
        self.lock.release()
        logging.debug("#D10008 Finishing message processor thread")

    def listen_messages(self, connection, client_address):
        # Logging section 9000
        logging.info('#E9001 %s connected.' % client_address[0])
        self.lock.acquire()
        logging.debug("#D9001 Adding new client %s to threads array" % client_address[0])
        self.clients.append(connection)
        self.lock.release()
        logging.debug("#D9002 Sending welcome message to client %s" % client_address[0])
        connection.send("#" + 'J14 HTTP-Savant Relay v%s\r\n' % server_version)
        time.sleep(2)
        logging.debug("#D9003 Pushing all device states to client %s" % client_address[0])
        self.httpcomms.new_connect(connection)
        while True:
            datarecv = connection.recv(1024)
            logging.debug("##D9004 Received data from %s" % client_address[0])
            if not datarecv:
                logging.debug("#D9005 Invalid data received from %s. Closing client connection" % client_address[0])
                break
            datarecv = datarecv.replace('\n', '')
            datarecv = datarecv.replace('\r', '')
            data = datarecv
            if data.encode('hex') == 'fffb06':
                logging.debug("#D9006 Received ^C from client %s. Closing client connection" % client_address[0])
                connection.close()
                break
            if data == 'close' or data == 'exit' or data == 'quit':
                logging.debug("#D9007 Received close, exit, or quit string from client %s. "
                              "Closing client connection" % client_address[0])
                break
            elif data == '':
                logging.debug("#D9008 Received empty data string from client %s" % client_address[0])
                connection.send("#32" + 'Empty Command String\r\n')
            else:
                try:
                    logging.debug("#D9009 Received command from client: %s" % client_address[0])
                    command = data
                    split_data = command.split('%')
                    try:
                        command = split_data[0]
                        body = split_data[1]
                        return_data = self.httpcomms.send_command(cmd_type='put', command=command,
                                                                  body=json.loads(body))
                        try:
                            for update in json.loads(return_data):
                                if 'success' in update:
                                    for key in update['success']:
                                        keys = key.strip("/").split("/")
                                        if update['success'][key] == "0":
                                            mydata = {keys[2]: {keys[3]: update['success'][key]}}
                                            if keys[3] == "on" and not bool(update['success'][key]):
                                                mydata[keys[2]]["bri"] = "0"
                                            connection.send("#" + json.dumps(
                                                {keys[0].rstrip('s'): {"id": keys[1], "info": mydata}}) + '\r\n')
                                        else:
                                            connection.send("#" + json.dumps(update) + '\r\n')
                                else:
                                    connection.send("#" + json.dumps(update) + '\r\n')
                        except TypeError:
                                connection.send("#" + json.dumps(return_data) + '\r\n')
                    
                    except IndexError:
                        return_data = self.httpcomms.send_command(cmd_type='get', command=command)
                        for item in return_data:
                            if command == "lights":
                                if not return_data[item]['state']['on']:
                                    return_data[item]['state']['bri'] = 0
                                    return_data[item]['state']['hue'] = 0
                                    return_data[item]['state']['sat'] = 0
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
                            connection.send("#" + json.dumps(
                                {command.rstrip("s"): {"id": item, "info": return_me}}) + '\r\n')
                    except TypeError:
                        logging.debug("#D9012 TypeError, could not process received data from client %s"
                                      % client_address[0])
                        connection.send('#D9012 TypeError, could not process received data\r\n')

                except ValueError:
                    logging.debug("#D9010 ValueError, could not process received data from client %s"
                                  % client_address[0])
                    connection.send('#D9010 ValueError, could not process received data\r\n')
                except TypeError:
                    logging.debug("#D9011 TypeError, could not process received data from client %s"
                                  % client_address[0])
                    connection.send('#D9011 TypeError, could not process received data\r\n')
                except Exception as err2:
                    logging.error('#E9001 %s\r\n' % err2)
                    connection.send('#E9001 %s\r\n' % err2)

        logging.debug("#D9012 Client %s thread closing" % client_address[0])
        self.lock.acquire()
        logging.debug("#D9013 Removing client %s from clients array, and thread from threads array"
                      % client_address[0])
        self.clients.remove(connection)
        self.threads.remove(threading.currentThread())
        self.lock.release()
        connection.close()
        logging.info('#I9002 %s disconnected.' % client_address[0])


class HTTPBridge(threading.Thread):
    # Logging section 8000
    def __init__(self, savant_queue):
        threading.Thread.__init__(self)
        self.message_queue = savant_queue
        self.lock = threading.Lock()
        self.threads = []
        self.store = {"lights": {}, "groups": {}, "sensors": {}, "scenes": {}, "all": {}}
        logging.debug("#D8001 HTTPBridge started")

    def run(self):
        logging.debug("#D8002 Setting up device poller")
        poller = threading.Thread(target=self.http_poller, args=())
        poller.setDaemon(True)
        poller.start()
        logging.debug("#D8003 Adding device poller thread to threads array")
        self.lock.acquire()
        self.threads.append(poller)
        self.lock.release()

    def http_poller(self):
        # Logging section 7000
        logging.debug("#D7001 Device poller started")
        while True:
            try:
                logging.debug("#D7002 Asking for device statuses from %s" % http_ip_address)
                result = self.send_command()
                logging.debug("#D7003 Received update successfully. Processing data...")

                try:
                    del result['config']
                    del result['resourcelinks']
                    del result['rules']
                    # del result['scenes']
                    del result['schedules']
                except KeyError:
                    pass

                if not self.store['all'] == result:
                    logging.debug("#D7004 HTTP Data chanced since last poll")
                    self.store["all"] = copy.deepcopy(result)
                    #
                    # Lights
                    #
                    for light_id in result['lights']:
                        light_data = result['lights'][light_id]

                        if light_id not in self.store["lights"]:
                            logging.debug("#D7005 Found a new LightID '%s', adding it to monitored lights" % light_id)
                            self.store["lights"][light_id] = copy.deepcopy(light_data)
                        try:
                            if not self.store["lights"][light_id] == light_data:
                                logging.debug("#D7006 Light '%s' information has changed"
                                              % light_id)
                                self.store["lights"][light_id] = copy.deepcopy(light_data)
                                logging.debug("#D7007 Notifying all clients of level change for light '%s'"
                                              % light_id)
                                if not light_data['state']['on']:
                                    light_data['state']['bri'] = 0
                                    light_data['state']['hue'] = 0
                                    light_data['state']['sat'] = 0
                                self.message_queue.put("#" + json.dumps(
                                    {"light": {"id": light_id, "info": light_data}}))
                        except Exception as err4:
                            logging.error("#E7001: %s" % err4.message)
                    #
                    # Groups
                    #
                    for group_id in result['groups']:
                        if result["groups"][group_id]["type"] in devicetypes:
                            group_data = result['groups'][group_id]
                            if group_id not in self.store["groups"]:
                                logging.debug("#D7008 Found a new GroupID '%s', adding it to monitored groups"
                                              % group_id)
                                self.store["groups"][group_id] = copy.deepcopy(group_data)
                            try:
                                if not self.store["groups"][group_id] == group_data:
                                    logging.debug("#D7009 Group '%s' information has changed"
                                                  % group_id)
                                    self.store["groups"][group_id] = copy.deepcopy(group_data)
                                    logging.debug("#D7010 Notifying all clients of level change for group '%s'"
                                                  % group_id)
                                    if not group_data['action']['on']:
                                        group_data['action']['bri'] = 0
                                        group_data['action']['hue'] = 0
                                        group_data['action']['sat'] = 0
                                    self.message_queue.put("#" + json.dumps(
                                        {"group": {"id": group_id, "info": group_data}}))
                            except Exception as err4:
                                logging.error("#E7002 %s" % err4.message)
                    #
                    # Sensors
                    #
                    for sensor_id in result['sensors']:
                        if result["sensors"][sensor_id]["modelid"] in devicetypes:
                            sensor_data = result['sensors'][sensor_id]
                            if sensor_id not in self.store["sensors"]:
                                logging.debug("#D7011 Found a new SensorID '%s', adding it to monitored "
                                              "sensors" % sensor_id)
                                self.store["sensors"][sensor_id] = copy.deepcopy(sensor_data)
                            try:
                                if not self.store["sensors"][sensor_id] == sensor_data:
                                    logging.debug("#D7012 Sensor '%s' information has changed"
                                                  % sensor_id)
                                    self.store["sensors"][sensor_id] = copy.deepcopy(sensor_data)
                                    logging.debug("#D7013 Notifying all clients of level change for sensor '%s'"
                                                  % sensor_id)
                                    self.message_queue.put("#" + json.dumps({
                                        "sensor": {"id": sensor_id, "info": sensor_data}}))
                            except Exception as err4:
                                logging.error("#E7003 %s" % err4.message)

            except Exception as err:
                logging.error(err)
                logging.error("#E7004 %s" % err)

            logging.debug("#D7014 Finished poll. Waiting for next poll.")
            time.sleep(http_poll_interval)

    def send_command(self, cmd_type='get', command='', body=None):
        # Logging section 6000
        if body is None:
            body = {}
        logging.debug("#D6001 Sending command to controller")
        try:
            if cmd_type == 'get':
                if command:
                    result = json.loads(urllib2.urlopen("http://%s/api/%s/%s" % (http_ip_address, http_key, command),
                                                        timeout=4).read())
                else:
                    result = json.loads(urllib2.urlopen("http://%s/api/%s" % (http_ip_address, http_key),
                                                        timeout=4).read())
            elif cmd_type == 'put':
                if "bri" in body:
                    if body['bri'] < 1:
                        body['on'] = False
                        body.pop('bri', None)
                request = urllib2.Request("http://%s/api/%s/%s" % (http_ip_address, http_key,
                                                                   command), json.dumps(body))
                request.get_method = lambda: 'PUT'
                result = urllib2.urlopen(request, timeout=4).read()
            else:
                if command:
                    result = json.loads(urllib2.urlopen(urllib2.Request(
                        "http://%s/api/%s/%s" % (http_ip_address, http_key, command), json.dumps(body)),
                        timeout=4).read())
                else:
                    result = json.loads(urllib2.urlopen(urllib2.Request(
                        "http://%s/api/%s" % (http_ip_address, http_key), json.dumps(body)), timeout=4).read())

            logging.debug("#D6002 Command ('%s') sent successfully" % command)
            return result

        except Exception as err:
            logging.error('#E6001 Error sending Command. HTTP Request failed. %s' % err)
            self.message_queue.put("#" + "Invalid HTTP command")

    def new_connect(self, connection):
        # Logging section 5000
        logging.debug("#D5001 New client connected. Sending all device states")
        #
        # Lights
        #
        for light_id in self.store['lights']:
            light_data = self.store['lights'][light_id]
            if not light_data['state']['on']:
                light_data['state']['bri'] = 0
                light_data['state']['hue'] = 0
                light_data['state']['sat'] = 0
            connection.send("#" + json.dumps({"light": {"id": light_id, "info": light_data}}) + '\r\n')
        #
        # Groups
        #
        for group_id in self.store['groups']:
            group_data = self.store['groups'][group_id]
            if not group_data['action']['on']:
                group_data['action']['bri'] = 0
                group_data['action']['hue'] = 0
                group_data['action']['sat'] = 0
            connection.send("#" + json.dumps({"group": {"id": group_id, "info": group_data}}) + '\r\n')
        #
        # Sensors
        #
        for sensor_id in self.store['sensors']:
            sensor_data = self.store['sensors'][sensor_id]
            connection.send("#" + json.dumps({"sensor": {"id": sensor_id, "info": sensor_data}}) + '\r\n')
        #
        # Scenes
        #
        for scene_id in self.store['all']['scenes']:
            scene_data = self.store['all']['scenes'][scene_id]
            if len(scene_data["appdata"]) > 0:
                connection.send("#" + json.dumps(
                    {"scene": {"id": scene_id, "info": {"name": scene_data["name"], "lights": ', '
                        .join(scene_data["lights"])}}}
                ) + '\r\n')

        logging.debug("#D5002 States sent successfully")


def run():
    # Logging section 4000
    queue = Queue(maxsize=50)
    try:
        logging.debug("#D4001 Starting the HTTP communications thread")
        httpcomms = HTTPBridge(queue)
        logging.debug("#D4002 Starting the Savant communications thread")
        CommunicationServer(queue, httpcomms).start()
        while True:
            time.sleep(5)

    except KeyboardInterrupt:
        queue.put('shutdown')
        logging.info('#I4001 KeyboardInterrupt detected, shutting down server')
        raise SystemExit
    except Exception as err0:
        queue.put('shutdown')
        logging.error("#E4001" + err0.message)
    finally:
        logging.debug("#D4003 Hit end of 'run()' function")
        queue.put('shutdown')


def discover_http():
    # Logging section 3000
    try:
        result = json.loads(urllib2.urlopen("http://www.meethue.com/api/nupnp", timeout=4).read())[0]
        return result['internalipaddress']
    except Exception as err:
        logging.error("E3002 " + err.message)
        return False


def register_api_key(ip_address):
    # Logging section 2000
    while True:
        try:
            logging.debug("#D2001 Obtaiing API key from: %s" % ip_address)
            result = json.loads(urllib2.urlopen(urllib2.Request("http://%s/api" % ip_address, json.dumps(
                {"devicetype": "HTTPBridge"})), timeout=4).read())[0]
            if 'error' in result:
                logging.error(json.dumps({"E2001 error": {"description": result["error"]["description"]}}))
                time.sleep(10)
            else:
                logging.debug("D2002 API key successfully created: %s" % result["success"]["username"])
                return result["success"]["username"]
        except Exception as err:

            logging.error("E2002 " + err.message)
            return False


def load_settings(ip_address, key, cur_settings=None):
    # Logging section 1000
    if cur_settings is None:
        cur_settings = {}
    global http_key
    global http_ip_address
    logging.debug('#D1001 Loading settings')
    if ip_address == "":
        try:
            http_ip_address = cur_settings['internalipaddress']
            if http_ip_address:
                logging.debug('#D1002 IP address set to %s from settings file' % http_ip_address)
            else:
                http_ip_address = discover_http()
                logging.debug('#D1003 IP address set to %s from discovery' % http_ip_address)
                if not http_ip_address:
                    logging.error('#E1001 Unable to find HTTP IP address, shutting down')
                    raise SystemExit

        except KeyError:
            http_ip_address = discover_http()
            logging.debug('#D1004 IP address set to %s from discovery' % http_ip_address)
            if not http_ip_address:
                logging.error('#E1002 Unable to find HTTP IP address, shutting down')
                raise SystemExit

    if key == "":
        try:
            http_key = cur_settings['key']
            if http_key:
                logging.debug('#D1005 API Key set to %s from settings file' % http_key)
            else:
                http_key = register_api_key(http_ip_address)
                logging.debug('#D1006 API Key set to %s from register' % http_key)
                if not http_key:
                    logging.error('#E1003 Unable to set API key, shutting down')
                    raise SystemExit
        except KeyError:
            http_key = register_api_key(http_ip_address)
            logging.debug('#D1007 API Key set to %s from register' % http_key)
            if not http_key:
                logging.error('#E1004 Unable to set API key, shutting down')
                raise SystemExit

    settings_data = {"key": http_key, "internalipaddress": http_ip_address}
    with open(settings_file, 'w') as set_file:
        json.dump(settings_data, set_file)


if __name__ == '__main__':
    # Logging Section #0000

    home = expanduser("~")

    # Argument parser and options
    parser = argparse.ArgumentParser(description="J14 HTTP-Savant Relay Server")
    parser.add_argument('-l', '--log', help="Logging Level: CRITICAL, ERROR, WARNING, INFO, DEBUG, NOTSET",
                        required=False, default="INFO")
    parser.add_argument('-d', '--debug', help="Set Logging Level to DEBUG",
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
                        required=False, default=['SML001', 'Room'], nargs='+')
    args = parser.parse_args()

    # Setup the logging engine
    if not args.debug:
        numeric_level = getattr(logging, args.log.upper(), None)
        if not isinstance(numeric_level, int):
            raise ValueError('Invalid log level: %s' % args.log)
    else:
        numeric_level = 10

    logging.basicConfig(format='%(asctime)s - %(levelname)s: %(message)s', filename=args.file, level=numeric_level)

    # Set up some global variables
    server_port = args.port
    http_ip_address = args.address
    http_key = args.key
    http_poll_interval = float(args.interval)
    max_reconnects = args.maxrecon
    reconnect_delay = args.recontime
    devicetypes = []
    settings_file = "%s/savant-hue.json" % home

    # Create an array of device types to monitor
    for watchtype in args.type:
        logging.debug("#D0001 Adding device type '%s' to monitor" % watchtype)
        devicetypes.append(watchtype)

    # Load settings
    if http_key == "" or http_ip_address == "":
        try:
            with open(settings_file, 'r') as fp:
                file_settings = json.load(fp)
            load_settings(http_ip_address, http_key, file_settings)
        except IOError:
            logging.error("#E0001 No Settings File, creating new file and adding settings")
            new_settings_data = {"key": "", "internalipaddress": ""}
            with open(settings_file, 'w') as fp:
                json.dump(new_settings_data, fp)
            load_settings(http_ip_address, http_key)
            file_settings = {"internalipaddress": http_ip_address, "key": http_key}
            with open(settings_file, 'w') as fp:
                json.dump(file_settings, fp)

    # Spit out some debug information to start with
    logging.debug("#D0002 Relay started")
    logging.debug("#D0003 Logging level = %s" % args.log)
    logging.debug("#D0004 Logfile = %s" % args.file)
    logging.debug("#D0005 Server Port = %s" % args.port)
    logging.debug("#D0006 HTTP key = %s" % http_key)
    logging.debug("#D0007 HTTP IP address = %s" % http_ip_address)
    logging.debug("#D0008 HTTP polling interval = %s" % args.interval)

    while True:
        logging.debug("#D0009 Starting main loop")
        if max_reconnects > 1:
            try:
                logging.debug("#D0010 Starting 'run()' function")
                run()
            except socket.error, err5:
                logging.error('#E0002 Connect error:', err5[1])
                reconnect_delay *= 2
            logging.info('#I0001 Waiting', reconnect_delay, 'seconds before restart.')
            logging.info('#I0002 Will try', max_reconnects, 'more times before shutdown')
            max_reconnects -= 1
            time.sleep(reconnect_delay)
            logging.info('#I0003 Restarting...')
        else:
            logging.debug("#D0011 End of script, exiting")
            logging.info('#I0004 EOL, goodbye')
            raise SystemExit
