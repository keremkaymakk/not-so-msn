import json
import os
import queue
import socket
import threading

PEER_CONNECT_TIMEOUT_SECONDS = 10
DOWNLOAD_DIRECTORY = os.path.join(os.getcwd(), "download")


class ClientNetwork:
    """
    The socket and P2P connection handler class.
    """

    def __init__(self, server_ip, server_port, username, gui, network_queue, response_queue):
        self.server_ip = server_ip
        self.server_port = int(server_port)
        self.username = username
        self.gui = gui
        self.network_queue = network_queue
        self.response_queue = response_queue

        self.is_running = False
        self.server_socket = None          # connection to the central server
        self.peer_listening_socket = None  # other peers connect to us here
        self.peer_listening_port = None
        self.own_ip_address = None

        # username -> {"ip": "...", "port": 1234}  (filled from USERLIST packets)
        self.online_users = {}
        self.online_users_lock = threading.Lock()

        # Outgoing messages are sent one by one by a single thread, so their order is kept
        self.outgoing_message_queue = queue.Queue()

        # Optional object written by the file transfer teammate (see set_file_transfer_handler)
        self.file_transfer_handler = None

        self.log_file_path = f"client_{username}.log"
        self.log_lock = threading.Lock()


    # 1) START: random port + P2P listening + register to the server

    def start(self):

        os.makedirs(DOWNLOAD_DIRECTORY, exist_ok=True)   # incoming files are stored here
        self.peer_listening_socket, self.peer_listening_port = self._open_listening_socket_on_random_port()

        try:
            self.server_socket = socket.create_connection((self.server_ip, self.server_port))
        except OSError as error:
            self._show_output(f"SYSTEM > Could not connect to the server: {error}")
            self.peer_listening_socket.close()
            return

        # The IP address of our network interface that reaches the server
        self.own_ip_address = self.server_socket.getsockname()[0]
        self.is_running = True

        self._send_to_server({
            "type": "REGISTER",
            "username": self.username,
            "ip": self.own_ip_address,
            "port": self.peer_listening_port,
        })

        self._start_background_thread(self._listen_for_server_updates)
        self._start_background_thread(self._accept_peer_connections)
        self._start_background_thread(self._send_queued_messages)

        self._show_output(
            f"SYSTEM > Connected as {self.username} ({self.own_ip_address}:{self.peer_listening_port})"
        )

    @staticmethod
    def _open_listening_socket_on_random_port():
        """Port 0 asks the operating system for a random available port."""
        listening_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listening_socket.bind(("", 0))
        listening_socket.listen()
        chosen_port = listening_socket.getsockname()[1]
        return listening_socket, chosen_port


    # 2) USERLIST: thread that listens to the server

    def _listen_for_server_updates(self):
        """The server sends the whole userlist every time someone connects or disconnects."""
        try:
            server_reader = self.server_socket.makefile("r", encoding="utf-8")
            for line in server_reader:
                line = line.strip()
                if not line:
                    continue
                packet = json.loads(line)
                if packet.get("type") == "USERLIST":
                    with self.online_users_lock:
                        self.online_users = packet["users"]
                    self.network_queue.put(("USER_DICT", json.dumps(packet["users"])))
        except (OSError, ValueError):
            pass   # socket closed or bad data -> fall through

        if self.is_running:   # we did not ask to disconnect, so the server went away
            self._show_output("SYSTEM > Connection to the server was lost.")

    def get_user_address(self, username):
        """Returns (ip, port) of an online user, or None if the user is not online."""
        with self.online_users_lock:
            user_info = self.online_users.get(username)
        if user_info is None:
            return None
        return user_info["ip"], int(user_info["port"])


    # 3a) SNDMSG: sending text messages

    def send_message(self, target_username, message):

        self.outgoing_message_queue.put((target_username, message))

    def _send_queued_messages(self):
        while self.is_running:
            try:
                target_username, message = self.outgoing_message_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            self._send_one_message(target_username, message)

    def _send_one_message(self, target_username, message):
        target_address = self.get_user_address(target_username)
        if target_address is None:
            self._show_output(f"SYSTEM > {target_username} is not online.")
            return

        target_ip, target_port = target_address
        try:
            with socket.create_connection(target_address, timeout=PEER_CONNECT_TIMEOUT_SECONDS) as peer_socket:
                peer_socket.sendall(f"MSG|{self.username}|{message}\n".encode("utf-8"))
        except OSError as error:
            self._show_output(f"SYSTEM > Could not send message to {target_username}: {error}")
            return

        self._show_output(f"{self.username} > {message}")
        self.write_log(f"Message to {target_username}@{target_ip}:{target_port} “{message}”")


    # 3b) Receiving from peers (messages here, files are delegated)

    def _accept_peer_connections(self):
        while self.is_running:
            try:
                peer_socket, _peer_address = self.peer_listening_socket.accept()
            except OSError:
                break   # listening socket was closed by disconnect()
            self._start_background_thread(self._handle_peer_connection, peer_socket)

    def _handle_peer_connection(self, peer_socket):
        try:
            peer_reader = peer_socket.makefile("rb")
            first_line = peer_reader.readline().decode("utf-8").rstrip("\r\n")

            if first_line.startswith("MSG|"):
                self._receive_message(first_line)

            elif first_line.startswith("FILE_REQ|") and self.file_transfer_handler is not None:
                # File teammate's code takes over this connection (it must not close the socket;
                # we close it in finally).
                self.file_transfer_handler.handle_incoming_file(peer_socket, peer_reader, first_line)

        except (OSError, ValueError, UnicodeDecodeError) as error:
            self._show_output(f"SYSTEM > Error while receiving from a peer: {error}")
        finally:
            peer_socket.close()

    def _receive_message(self, message_line):
        # maxsplit=2 so that a '|' inside the message content is kept
        _, sender_username, message = message_line.split("|", 2)
        self._show_output(f"{sender_username} > {message}")
        self.write_log(f"Message from {self.describe_user(sender_username)} “{message}”")

    # =====================================================================
    # File transfer hook (implemented by another teammate)
    # =====================================================================
    def set_file_transfer_handler(self, file_transfer_handler):
        """
        The file module gives an object with two methods:
            send_file(target_username, filepath)
            handle_incoming_file(peer_socket, peer_reader, first_line)
        It can use self.get_user_address, self.write_log, self.describe_user,
        self.network_queue and self.response_queue.
        """
        self.file_transfer_handler = file_transfer_handler

    def send_file(self, target_username, filepath):
        """Called after 'sndf' command is parsed in GUI."""
        if self.file_transfer_handler is None:
            self._show_output("SYSTEM > File transfer is not available yet.")
            return
        self.file_transfer_handler.send_file(target_username, filepath)

    # =====================================================================
    # 4) DISCONNECT
    # =====================================================================
    def disconnect(self):
        """
        Called after Disconnect button (or the window's X) is pressed on the GUI.
        Tells the server we are leaving and closes all sockets.
        """
        if not self.is_running:
            return
        self.is_running = False   # background loops stop at their next check

        try:
            self._send_to_server({"type": "DISCONNECT"})
        except OSError:
            pass   # server may already be gone

        for open_socket in (self.server_socket, self.peer_listening_socket):
            try:
                open_socket.close()
            except OSError:
                pass


    # Small helpers (also usable by the file transfer module)

    def _send_to_server(self, packet):
        self.server_socket.sendall((json.dumps(packet) + "\n").encode("utf-8"))

    def _show_output(self, text):
        self.network_queue.put(("OUTPUT", text))

    def _start_background_thread(self, target_function, *arguments):
        threading.Thread(target=target_function, args=arguments, daemon=True).start()

    def describe_user(self, username):
        """Returns 'name@ip:port' for the log file (just the name if the user is not in the list)."""
        user_address = self.get_user_address(username)
        if user_address is None:
            return username
        return f"{username}@{user_address[0]}:{user_address[1]}"

    def write_log(self, line):
        with self.log_lock:
            with open(self.log_file_path, "a", encoding="utf-8") as log_file:
                log_file.write(line + "\n")
