import sys
import queue
import json
import socket
import threading
import tkinter as tk
from tkinter import messagebox


class ClientGUI:
    """
    The client GUI handler class.
    """

    def __init__(self, root, username, network_queue, response_queue):
        self.root = root
        self.username = username
        self.network_queue = network_queue
        self.response_queue = response_queue
        self.network = None

        self.root.protocol("WM_DELETE_WINDOW", self._on_disconnect)
        self.root.after(100, self._process_queue)

    def _process_queue(self):
        """
        The method that is used to process the incoming network queue.
        """
        try:
            while True:
                item = self.network_queue.get_nowait()
                msg_type, data = item

                if msg_type == 'OUTPUT':
                    self._append_output(data)
                elif msg_type == 'USER_DICT':
                    self._update_user_dict(data)
                elif msg_type == 'FILE_PROMPT':
                    payload = json.loads(data)
                    sender = payload.get('sender')
                    filename = payload.get('filename')
                    prompt_id = payload.get('prompt_id')

                    accepted = self.prompt_file_acceptance(sender, filename)

                    response_payload = {
                        'prompt_id': prompt_id,
                        'accepted': accepted
                    }
                    self.response_queue.put_nowait(json.dumps(response_payload))

        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._process_queue)

    def set_network(self, network):
        """
        Binds the ClientNetwork instance to the GUI.
        """
        self.network = network

    def _on_execute(self):
        """
        The method called when the execute button is pressed.
        """
        return

    def _on_disconnect(self):
        """
        The method called when the disconnect button is pressed.
        """
        return

    def _append_output(self, text):
        """
        Appends a text to the output area.
        """
        return

    def _update_user_dict(self, user_dict):
        """
        Reloads the user dictionary.

        :param user_dict: A JSON string, with a sample entry on the outer dictionary being:
                            "<username>": {
                                "ip": "<ip address>",
                                "port": <port number>   # Be careful that the port value is an integer
                            }
        """
        return

    def get_selected_user(self):
        """
        Returns the username selected in the user listbox.
        """
        return

    def prompt_file_acceptance(self, sender_username, filename):
        """
        Displays a confirmation pop-up screen to accept/reject an incoming file transfer request.
        Returns True if accepted, or False if rejected.
        :param sender_username: Sender username to display.
        :param filename: Filename to display.
        :return: True if accepted, or False if rejected.
        """
        return


class ClientNetwork:
    """
    The socket and P2P connection handler class.
    """

    def __init__(self, server_ip, server_port, username, gui, network_queue, response_queue):
        """
        ClientNetwork constructor.

        :param server_ip: IP address of the server.
        :param server_port: Port number of the server.
        :param username: Username string of client user.
        :param gui: ClientGUI instance to display the GUI.
        :param network_queue: Queue of incoming network request tuples. Format: ("<TYPE>", "<data>")
        :param response_queue: Queue of user responses to prompts. Format: JSON string '{"prompt_id": ..., "accepted": ...}'
        """
        self.server_ip = server_ip
        self.server_port = server_port
        self.username = username
        self.gui = gui
        self.network_queue = network_queue
        self.response_queue = response_queue

    def start(self):
        """
        Starts listening on an available port, registers to central server, and launches background listener threads.
        """
        pass

    def send_message(self, target_username, message):
        """
        Called after 'sndmsg' command is parsed in GUI. Using the target user's IP/Port info, sends
        'MSG|<username>|<message>'.
        (Must run on a background thread to not block any other threads.)
        """
        pass

    def send_file(self, target_username, filepath):
        """
        Called after 'sndf' command is parsed in GUI. Using the target user's IP/Port info,
        starts a 3-step file transfer protocol (FILE_REQ -> FILE_ACC -> Chunk Transfer)
        in a different worker thread.
        """
        pass

    def disconnect(self):
        """
        Called after Disconnect button is pressed on the GUI.
        """
        pass


def main():
    if len(sys.argv) < 4:
        print("Usage: python client <server-ip-address> <server-port-number> <user-name>")
        sys.exit(1)

    # Read the command line arguments
    server_ip = sys.argv[1]
    server_port = int(sys.argv[2])
    client_username = sys.argv[3]


    """
    Network Threads -> GUI
    Queue of incoming network request tuples. Entry tuple format is: ("<TYPE>", "<data>")
    
    
    Three kinds of entries:
    
    1- ("OUTPUT", "<Display Message>")
        e.g. ("OUTPUT", "Zoktay > Merhaba")
    
    2- ("USER_DICT", "<User Dictionary in JSON format>")
        e.g. ("USER_DICT", "{"Dipper": {"ip": "123.123.123.123", "port": 123}}")
    
    3- ("FILE_PROMPT", "<Prompt info in JSON format>")
        e.g. ("FILE_PROMPT", "{"sender": "Mesut Komiser", "filename": "ğığığı.mp3", "prompt_id": "751"}")
    """
    network_queue = queue.Queue()


    """
    GUI -> Network Threads
    Used in file acceptance/transmission. Entry JSON string format is: 
        "{
            "prompt_id": "<prompt ID>",
            "accepted": <True/False>
        }"
    """
    response_queue = queue.Queue()
    """
        Note on response_queue usage in ClientNetwork:
        When an incoming file transfer request arrives:
          1. Generate a unique 'prompt_id' (A random string, perhaps a random integer parsed as string).
          2. Put the request to network_queue:
             network_queue.put(("FILE_PROMPT", json.dumps({"sender": sender, "filename": filename, "prompt_id": prompt_id})))
          3. Wait for the user's GUI response (blocking with timeout or polling):
             # Example:
             res = json.loads(response_queue.get())
             if res["prompt_id"] == prompt_id and res["accepted"]:
                 # Start file transfer
             else:
                 # Reject file transfer
        """

    # Start the TKinter GUI
    root = tk.Tk()
    gui = ClientGUI(root, client_username, network_queue, response_queue)

    # Start connection threads and bind to GUI
    """
        Note: 
        Please use ClientNetwork class to write code in. 
        
        Please see the docstrings on how to use them.
        
        Also, in incoming network requests, please use network_queue.put(<Queue entry>).
        See the entry format in network_queue description.
    """
    network = ClientNetwork(server_ip, server_port, client_username, gui, network_queue, response_queue)
    gui.set_network(network)
    network.start()

    # Run GUI main loop in the main thread
    root.mainloop()


if __name__ == "__main__":
    main()
