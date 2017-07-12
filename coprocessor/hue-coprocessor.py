#!/usr/bin/python
#     
#     'http-Savant Bridge'
#     Copyright (C) '2016'  J14 Technologies Ltd
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

try:
    import argparse
except ImportError:
    raise ImportError("Failed to import 'argparse'. Please install this module before continuing")

# Server version
server_version = '1.0'

# Script Notes:
# Last debug message number used


class CommunicationServer(threading.Thread):
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
            logging.info('Starting up CommunicationServer on %s, port %s' % self.server_address)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.TCP_NODELAY, 1)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1048576)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1048576)
            try:
                logging.debug("#7 Binding to socket")
                self.sock.bind(self.server_address)
                logging.debug("#8 Binding successful, lets listen to what it says")
                self.sock.listen(1)
                connection_loop = False
            except socket.error, socket_error:
                logging.error("We have a socket error. %s" % socket_error)
                time.sleep(10)
            except Exception as err1:
                self.message_queue.put('shutdown')
                logging.error("#Error1: %s" % err1.message)
        logging.debug("#9 Savant communications server started successfully")

    def run(self):
        logging.debug("#10 setting up the message queue processor")
        queue_processor = threading.Thread(target=self.process_queue, args=())
        queue_processor.setDaemon(True)
        logging.debug("#11 Starting the message queue processor")
        queue_processor.start()
        logging.debug("#12 Message queue processor started, adding a record of thread to threads array")
        self.lock.acquire()
        self.threads.append(queue_processor)
        self.lock.release()
        logging.debug("#13 Starting the HTTP communications server")
        self.httpcomms.start()
        while self.running:
            logging.debug("#14 Setting up a Savant connection listener")
            listen_process = threading.Thread(target=self.listen_messages, args=(self.sock.accept()))
            listen_process.setDaemon(True)
            logging.debug("#15 Starting the Savant connection listener")
            listen_process.start()
            logging.debug("#16 Adding connection listener to threads array")
            self.lock.acquire()
            self.threads.append(listen_process)
            self.lock.release()

        logging.info("Closing CommunicationsServer")
        self.sock.close()

    def process_queue(self):
        logging.debug("#17 Message queue processor started")
        while True:
            message = self.message_queue.get()
            logging.debug("#18 Message received: %s" % message)
            if message == 'shutdown':
                logging.debug("#19 Message 'Shutdown' received. Closing communications servers.")
                self.running = False
                logging.debug("#20 Force a new connection to break connection listener")
                sock2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock2.connect(self.server_address)
                time.sleep(1)
                break
            else:
                for client in self.clients:
                    try:
                        logging.debug("#21 Sending received message to client")
                        client.send(message + "\r\n")
                    except TypeError:
                        logging.debug("#22 Message format not right as string, formatting for JSON. "
                                      "Sending to client")
                        client.send(json.dumps(str(message)) + "\r\n")
        self.lock.acquire()
        logging.debug("#23 Removing message processor from threads array")
        self.threads.remove(threading.currentThread())
        self.lock.release()
        logging.debug("#24 Finishing message processor thread")

    def listen_messages(self, connection, client_address):
        logging.info('%s connected.' % client_address[0])
        self.lock.acquire()
        logging.debug("#25 Adding new client %s to threads array" % client_address[0])
        self.clients.append(connection)
        self.lock.release()
        logging.debug("#26 Sending welcome message to client %s" % client_address[0])
        connection.send('J14 HTTP-Savant Relay v%s\r\n' % server_version)
        time.sleep(2)
        logging.debug("#27 Pushing all device states to client %s" % client_address[0])
        self.httpcomms.new_connect(connection)
        while True:
            datarecv = connection.recv(1024)
            logging.debug("#28 Received data from %s" % client_address[0])
            if not datarecv:
                logging.debug("#29 Invalid data received from %s. Closing client connection" % client_address[0])
                break
            datarecv = datarecv.replace('\n', '')
            datarecv = datarecv.replace('\r', '')
            data = datarecv
            if data.encode('hex') == 'fffb06':
                logging.debug("#30 Received ^C from client %s. Closing client connection" % client_address[0])
                connection.close()
                break
            if data == 'close' or data == 'exit' or data == 'quit':
                logging.debug("#31 Received close, exit, or quit string from client %s. "
                              "Closing client connection" % client_address[0])
                break
            elif data == '':
                logging.debug("#32 Received empty data string from client %s" % client_address[0])
                connection.send('Invalid Command String or malformed JSON string\r\n')
            else:
                try:
                    logging.debug("#33 Received command from client: %s" % client_address[0])
                    command = data
                    split_data = command.split('%')
                    try:
                        command = split_data[0]
                        body = split_data[1]
                        return_data =  self.httpcomms.send_command(type='put', command=command, body=json.loads(body))
                        connection.send(return_data + '\r\n')
                    except IndexError:
                        return_data = self.httpcomms.send_command(type='get', command=command)
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
                                return_me = {"name": return_data[item]["name"], "lights": ', '.join(return_data[item]["lights"])}
                            elif command == "sensors":
                                if not return_data[item]["modelid"] in devicetypes:
                                    continue
                                return_me = return_data[item]
                            else:
                                return_me = return_data[item]

                            connection.send(json.dumps({command.rstrip("s"): {"id": item, "info": return_me}}) + '\r\n')


                except ValueError:
                    logging.debug("#35 ValueError, could not process received data from client %s" % client_address[0])
                    connection.send('Invalid Command String or malformed JSON string\r\n')
                except TypeError:
                    logging.debug("#36 TypeError, could not process received data from client %s" % client_address[0])
                    connection.send('Invalid Command String or malformed JSON string\r\n')
                except Exception as err2:
                    logging.error('# Error2: %s\r\n' % err2)
                    connection.send('# Error2: %s\r\n' % err2)

        logging.debug("#37 Client %s thread closing" % client_address[0])
        self.lock.acquire()
        logging.debug("#38 Removing client %s from clients array, and thread from threads array" % client_address[0])
        self.clients.remove(connection)
        self.threads.remove(threading.currentThread())
        self.lock.release()
        connection.close()
        logging.info('%s disconnected.' % client_address[0])


class HTTPBridge(threading.Thread):
    def __init__(self, savant_queue):
        threading.Thread.__init__(self)
        self.message_queue = savant_queue
        self.lock = threading.Lock()
        self.threads = []
        self.store = {"lights": {}, "groups": {}, "sensors": {}, "scenes": {}, "all": {}}
        logging.debug("#39 HTTPBridge started")

    def run(self):
        logging.debug("#40 Setting up device poller")
        poller = threading.Thread(target=self.http_poller, args=())
        poller.setDaemon(True)
        poller.start()
        logging.debug("#41 Adding device poller thread to threads array")
        self.lock.acquire()
        self.threads.append(poller)
        self.lock.release()

    def http_poller(self):
        logging.debug("#42 Device poller started")
        while True:
            try:
                logging.debug("#43 Asking for device statuses from %s" % http_ip_address)
                result = self.send_command()
                logging.debug("#44 Received update successfully. Processing data...")

                try:
                    del result['config']
                    del result['resourcelinks']
                    del result['rules']
                    # del result['scenes']
                    del result['schedules']
                except KeyError:
                    pass

                if not self.store['all'] == result:
                    logging.debug("#60 HTTP Data chanced since last poll")
                    self.store["all"] = copy.deepcopy(result)
                    #
                    # Lights
                    #
                    for light_id in result['lights']:
                        light_data = result['lights'][light_id]

                        if light_id not in self.store["lights"]:
                            logging.debug("#20 Found a new LightID '%s', adding it to monitored lights" % light_id)
                            self.store["lights"][light_id] = copy.deepcopy(light_data)
                        try:
                            if not self.store["lights"][light_id] == light_data:
                                logging.debug("#19 Light '%s' information has changed"
                                              % light_id)
                                self.store["lights"][light_id] = copy.deepcopy(light_data)
                                logging.debug("#18 Notifying all clients of level change for light '%s'"
                                              % light_id)
                                if not light_data['state']['on']:
                                    light_data['state']['bri'] = 0
                                    light_data['state']['hue'] = 0
                                    light_data['state']['sat'] = 0
                                self.message_queue.put(json.dumps({"light": {"id": light_id, "info": light_data}}))
                        except Exception as err4:
                            logging.error("#Error4: %s" % err4.message)
                    #
                    # Groups
                    #
                    for group_id in result['groups']:
                        if result["groups"][group_id]["type"] in devicetypes:
                            group_data = result['groups'][group_id]
                            if group_id not in self.store["groups"]:
                                logging.debug("#16 Found a new GroupID '%s', adding it to monitored groups" % group_id)
                                self.store["groups"][group_id] = copy.deepcopy(group_data)
                            try:
                                if not self.store["groups"][group_id] == group_data:
                                    logging.debug("#15 Group '%s' information has changed"
                                                  % group_id)
                                    self.store["groups"][group_id] = copy.deepcopy(group_data)
                                    logging.debug("#14 Notifying all clients of level change for group '%s'"
                                                  % group_id)
                                    if not group_data['action']['on']:
                                        group_data['action']['bri'] = 0
                                        group_data['action']['hue'] = 0
                                        group_data['action']['sat'] = 0
                                    self.message_queue.put(json.dumps({"group": {"id": group_id, "info": group_data}}))
                            except Exception as err4:
                                logging.error("#Error4: %s" % err4.message)
                    #
                    # Sensors
                    #
                    for sensor_id in result['sensors']:
                        if result["sensors"][sensor_id]["modelid"] in devicetypes:
                            sensor_data = result['sensors'][sensor_id]
                            if sensor_id not in self.store["sensors"]:
                                logging.debug("#12 Found a new SensorID '%s', adding it to monitored "
                                              "sensors" % sensor_id)
                                self.store["sensors"][sensor_id] = copy.deepcopy(sensor_data)
                            try:
                                if not self.store["sensors"][sensor_id] == sensor_data:
                                    logging.debug("#11 Sensor '%s' information has changed"
                                                  % sensor_id)
                                    self.store["sensors"][sensor_id] = copy.deepcopy(sensor_data)
                                    logging.debug("#10 Notifying all clients of level change for sensor '%s'"
                                                  % sensor_id)
                                    self.message_queue.put(json.dumps({"sensor": {"id": sensor_id,
                                                                                  "info": sensor_data}}))
                            except Exception as err4:
                                logging.error("#Error4: %s" % err4.message)

            except Exception as err:
                logging.error(err)
                logging.error("#Error3: %s" % err)

            logging.debug("#56 Finished poll. Waiting for next poll.")
            time.sleep(http_poll_interval)

    def send_command(self, type='get', command='', body={}):
        logging.debug("#57 Sending command to controller")
        try:
            if type == 'get':
                if command:
                    result = json.loads(urllib2.urlopen("http://%s/api/%s/%s" % (http_ip_address, http_key, command),
                                                        timeout=4).read())
                else:
                    result = json.loads(urllib2.urlopen("http://%s/api/%s" % (http_ip_address, http_key),
                                                        timeout=4).read())
            elif type == 'put':
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

            logging.debug("#60 Command ('%s') sent successfully" % command)
            return result

        except Exception as err:
            logging.error('Error sending Command. HTTP Request failed. %s' % err)
            self.message_queue.put("Invalid HTTP command")

    def new_connect(self, connection):
        logging.debug("#61 New client connected. Sending all device states")
        #
        # Lights
        #
        for light_id in self.store['lights']:
            light_data = self.store['lights'][light_id]
            if not light_data['state']['on']:
                light_data['state']['bri'] = 0
                light_data['state']['hue'] = 0
                light_data['state']['sat'] = 0
            connection.send(json.dumps({"light": {"id": light_id, "info": light_data}}) + '\r\n')
        #
        # Groups
        #
        for group_id in self.store['groups']:
            group_data = self.store['groups'][group_id]
            if not group_data['action']['on']:
                group_data['action']['bri'] = 0
                group_data['action']['hue'] = 0
                group_data['action']['sat'] = 0
            connection.send(json.dumps({"group": {"id": group_id, "info": group_data}}) + '\r\n')
        #
        # Sensors
        #
        for sensor_id in self.store['sensors']:
            sensor_data = self.store['sensors'][sensor_id]
            connection.send(json.dumps({"sensor": {"id": sensor_id, "info": sensor_data}}) + '\r\n')
        #
        # Scenes
        #
        for scene_id in self.store['all']['scenes']:
            scene_data = self.store['all']['scenes'][scene_id]
            if len(scene_data["appdata"]) > 0:
                connection.send(json.dumps(
                    {"scene": {"id": scene_id, "info": {"name": scene_data["name"], "lights": ', '
                        .join(scene_data["lights"])}}}
                ) + '\r\n')

        logging.debug("#62 States sent successfully")


def run():
    queue = Queue(maxsize=50)
    try:
        logging.debug("#4 Starting the HTTP communications thread")
        httpcomms = HTTPBridge(queue)
        logging.debug("#5 Starting the Savant communications thread")
        CommunicationServer(queue, httpcomms).start()
        while True:
            time.sleep(5)

    except KeyboardInterrupt:
        queue.put('shutdown')
        logging.info('KeyboardInterrupt detected, shutting down server')
        raise SystemExit
    except Exception as err0:
        queue.put('shutdown')
        logging.error(err0.message)
    finally:
        logging.debug("#6 Hit end of 'run()' function")
        queue.put('shutdown')


def discover_http():
    try:
        result = json.loads(urllib2.urlopen("http://www.meethue.com/api/nupnp", timeout=4).read())[0]
        return result['internalipaddress']
    except Exception as err:
        logging.error(err)
        return False


def register_api_key(ip_address):
    while True:
        try:
            logging.debug("#106 Obtaiing API key from: %s" % ip_address)
            result = json.loads(urllib2.urlopen(urllib2.Request("http://%s/api" % ip_address, json.dumps({
                "devicetype": "HTTPBridge"})), timeout=4).read())[0]
            if result['error']:
                logging.error(json.dumps({"error": {"description": result["error"]["description"]}}))
                time.sleep(10)
            else:
                logging.debug("#101 API key successfully created: %s" % result["success"]["username"])
                return result["success"]["username"]
        except Exception as err:
            logging.error(err)
            return False


def load_settings(ip_address, key, cur_settings={}):
    global http_key
    global http_ip_address
    logging.debug('#200 Loading settings')
    if ip_address == "":
        try:
            http_ip_address = cur_settings['internalipaddress']
            if http_ip_address:
                logging.debug('#201 IP address set to %s from settings file' % http_ip_address)
            else:
                http_ip_address = discover_http()
                logging.debug('#204 IP address set to %s from discovery' % http_ip_address)
                if not http_ip_address:
                    logging.error('#205 Unable to find HTTP IP address, shutting down')
                    raise SystemExit

        except KeyError:
            http_ip_address = discover_http()
            logging.debug('#202 IP address set to %s from discovery' % http_ip_address)
            if not http_ip_address:
                logging.error('#103 Unable to find HTTP IP address, shutting down')
                raise SystemExit

    if key == "":
        try:
            http_key = cur_settings['key']
            if http_key:
                logging.debug('#203 API Key set to %s from settings file' % http_key)
            else:
                http_key = register_api_key(http_ip_address)
                logging.debug('#205 API Key set to %s from register' % http_key)
                if not http_key:
                    logging.error('#206 Unable to set API key, shutting down')
                    raise SystemExit
        except KeyError:
            http_key = register_api_key(http_ip_address)
            logging.debug('#204 API Key set to %s from register' % http_key)
            if not http_key:
                logging.error('#202 Unable to set API key, shutting down')
                raise SystemExit

    settings_data = {"key": http_key, "internalipaddress": http_ip_address}
    with open('savant-hue.json', 'w') as set_file:
        json.dump(settings_data, set_file)


if __name__ == '__main__':
    # Argument parser and options
    parser = argparse.ArgumentParser(description="J14 HTTP-Savant Relay Server")
    parser.add_argument('-l', '--log', help="Logging Level: CRITICAL, ERROR, WARNING, INFO, DEBUG, NOTSET",
                        required=False, default="INFO")
    parser.add_argument('-d', '--debug', help="Set Logging Level to DEBUG",
                        required=False, action='store_true')
    parser.add_argument('-f', '--file', help="Logging File path",
                        required=False, default="http-savant.log")
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

    # Create an array of device types to monitor
    for watchtype in args.type:
        logging.debug("Adding device type '%s' to monitor" % watchtype)
        devicetypes.append(watchtype)

    # Load settings
    if http_key == "" or http_ip_address == "":
        try:
            with open('savant-hue.json', 'r') as fp:
                file_settings = json.load(fp)
            load_settings(http_ip_address, http_key, file_settings)
        except IOError:
            logging.error("#0 No Settings File, creating new file and adding settings")
            new_settings_data = {"key": "", "internalipaddress": ""}
            with open('savant-hue.json', 'w') as fp:
                json.dump(new_settings_data, fp)
            load_settings(http_ip_address, http_key)
            file_settings = {"internalipaddress": http_ip_address, "key": http_key}
            with open('savant-hue.json', 'w') as fp:
                json.dump(file_settings, fp)

    # Spit out some debug information to start with
    logging.debug("Relay started")
    logging.debug("Logging level = %s" % args.log)
    logging.debug("Logfile = %s" % args.file)
    logging.debug("Server Port = %s" % args.port)
    logging.debug("HTTP key = %s" % http_key)
    logging.debug("HTTP IP address = %s" % http_ip_address)
    logging.debug("HTTP polling interval = %s" % args.interval)

    while True:
        logging.debug("#1 Starting main loop")
        if max_reconnects > 1:
            try:
                logging.debug("#2 Starting 'run()' function")
                run()
            except socket.error, err5:
                logging.error('Connect error:', err5[1])
                reconnect_delay *= 2
            logging.info('Waiting', reconnect_delay, 'seconds before restart.')
            logging.info('Will try', max_reconnects, 'more times before shutdown')
            max_reconnects -= 1
            time.sleep(reconnect_delay)
            logging.info('Restarting...')
        else:
            logging.debug("#3 End of script, exiting")
            logging.info('EOL, goodbye')
            raise SystemExit
