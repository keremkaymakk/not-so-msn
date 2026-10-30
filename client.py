import sys
import queue
import json
import socket
import threading
import tkinter as tk
from tkinter import messagebox

from client_network import ClientNetwork  # 2. kişinin modülü
from file_transfer import FileTransferHandler  # 3. kişinin modülü


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

        # Window title and shape
        self.root.title(self.username)
        self.root.geometry('800x600')
        self.root.minsize(640, 480)

        # Grid structure 2x2
        self.root.grid_columnconfigure(0, weight=1)  # Left column can expand with the window
        self.root.grid_columnconfigure(1, weight=0, minsize=180)  # Right column size stays fixed
        self.root.grid_rowconfigure(0, weight=7)  # Top row takes more space
        self.root.grid_rowconfigure(1, weight=3)  # Bottom row takes less space

        # Top-left: Output (messages) area
        self.output_text = tk.Text(self.root, height=16, state=tk.DISABLED,
                                   wrap=tk.WORD)  # Uneditable and left-aligned text
        self.output_text.grid(row=0, column=0, sticky='nsew', padx=(10, 5), pady=(10, 5))

        # Bottom-left: Input (commands) area
        self.command_text = tk.Text(self.root, height=12, wrap=tk.NONE)  # Editable and non-aligned text
        self.command_text.grid(row=1, column=0, sticky='nsew', padx=(10, 5), pady=(5, 10))

        # Top-right: Userlist listbox
        top_right = tk.Frame(self.root)  # Frame of the top-right
        top_right.grid(row=0, column=1, sticky='nsew', padx=(5, 10), pady=(10, 5))

        tk.Label(top_right, text="Users", anchor='w').pack(fill=tk.X)
        self.user_listbox = tk.Listbox(top_right, selectmode=tk.SINGLE, exportselection=False)
        self.user_listbox.pack(fill=tk.BOTH, expand=True)

        # Bottom-right: Execute and disconnect buttons
        bottom_right = tk.Frame(self.root)  # Frame of the bottom-right
        bottom_right.grid(row=1, column=1, sticky='sew', padx=(5, 10), pady=(5, 10))

        self.execute_button = tk.Button(bottom_right, text="Execute", command=self._on_execute)
        self.execute_button.pack(fill=tk.X, pady=(0, 5))

        self.disconnect_button = tk.Button(bottom_right, text="Disconnect", command=self._on_disconnect)
        self.disconnect_button.pack(fill=tk.X)

        # Close window protocol and queue listener
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
        raw_commands = self.command_text.get('1.0', tk.END).strip()
        if not raw_commands:
            return

        target_user = self.get_selected_user()
        if not target_user:
            messagebox.showwarning("No user selected", "Please select a user from the list.")
            return

        for command in raw_commands.splitlines():
            command = command.strip()
            if not command:
                continue  # Skip the blank lines

            if command.startswith("sndmsg "):
                message = command[len("sndmsg "):].strip()
                if message and self.network:
                    self.network.send_message(target_user, message)

            elif command.startswith("sndf "):
                filepath = command[len("sndf "):].strip()

                # Quote mark trimming
                if (filepath.startswith("'") and filepath.endswith("'")) or (
                        filepath.startswith('"') and filepath.endswith('"')) or (
                        filepath.startswith('“') and filepath.endswith('”')):
                    filepath = filepath[1:-1].strip()

                if filepath and self.network:
                    self.network.send_file(target_user, filepath)

            else:
                self._append_output(f"SYSTEM > Unknown command: {command}")

        self.command_text.delete('1.0', tk.END)

    def _on_disconnect(self):
        """
        The method called when the disconnect button or 'X' button is pressed.
        """
        if self.network:
            try:
                self.network.disconnect()
            except Exception as e:
                print(f"Error while disconnecting: {e}")

        self.root.destroy()

    def _append_output(self, text):
        """
        Appends a text to the output area.
        """
        self.output_text.config(state=tk.NORMAL)
        self.output_text.insert(tk.END, text + "\n")
        self.output_text.see(tk.END)
        self.output_text.config(state=tk.DISABLED)

    def _update_user_dict(self, user_dict):
        """
        Reloads the user dictionary in the GUI.

        :param user_dict: A JSON string, with a sample entry on the outer dictionary being:
                            "<username>": {
                                "ip": "<ip address>",
                                "port": <port number>   # Be careful that the port value is an integer
                            }
        """
        previous_selection = self.get_selected_user()

        users = json.loads(user_dict)

        self.user_listbox.delete(0, tk.END)

        for idx, user in enumerate(users.keys()):
            if user == self.username:
                continue

            self.user_listbox.insert(tk.END, user)

            if user == previous_selection:
                self.user_listbox.selection_set(idx)

    def get_selected_user(self):
        """
        Returns the username selected in the user listbox.
        """
        selection = self.user_listbox.curselection()
        if selection:
            return self.user_listbox.get(selection[0])
        return None

    def prompt_file_acceptance(self, sender_username, filename):
        """
        Displays a confirmation pop-up screen to accept/reject an incoming file transfer request.
        Returns True if accepted, or False if rejected.
        :param sender_username: Sender username to display.
        :param filename: Filename to display.
        :return: True if accepted, or False if rejected.
        """
        return messagebox.askyesno(
            "Incoming file transfer request",
            f"'{sender_username}' wants to send you the file:\n'{filename}'\n\nDo you accept to download this file?"
        )


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

    network = ClientNetwork(server_ip, server_port, client_username, gui, network_queue, response_queue)
    gui.set_network(network)
    network.set_file_transfer_handler(FileTransferHandler(network))
    network.start()

    # Run GUI main loop in the main thread
    root.mainloop()


if __name__ == "__main__":
    main()