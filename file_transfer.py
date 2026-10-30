import json
import os
import socket
import threading
import uuid

from client_network import DOWNLOAD_DIRECTORY, PEER_CONNECT_TIMEOUT_SECONDS

FILE_CHUNK_SIZE = 4096


class FileTransferHandler:
    """
    Sends and receives files between peers with a 3-step handshake:
        1) sender -> receiver : FILE_REQ|<sender_username>|<filename>|<file_size>
        2) receiver -> sender : FILE_ACC  or  FILE_REJ   (the user decides in a message box)
        3) sender -> receiver : the raw file bytes, in 4096 byte chunks
    """

    def __init__(self, network):
        self.network = network

        # prompt_id -> {"answered": threading.Event(), "accepted": bool}
        self.pending_prompts = {}
        self.pending_prompts_lock = threading.Lock()

        threading.Thread(target=self._dispatch_gui_responses, daemon=True).start()


    # GUI answers: the GUI puts every yes/no answer into one shared response_queue,
    # so a single thread hands each answer to the transfer that is waiting for it.

    def _dispatch_gui_responses(self):
        while True:
            response = json.loads(self.network.response_queue.get())
            with self.pending_prompts_lock:
                pending_prompt = self.pending_prompts.get(response["prompt_id"])
            if pending_prompt is None:
                continue
            pending_prompt["accepted"] = bool(response["accepted"])
            pending_prompt["answered"].set()

    def _ask_user_to_accept(self, sender_username, filename):
        """Shows the confirmation box on the GUI and blocks until the user answers."""
        prompt_id = uuid.uuid4().hex
        pending_prompt = {"answered": threading.Event(), "accepted": False}
        with self.pending_prompts_lock:
            self.pending_prompts[prompt_id] = pending_prompt

        self.network.network_queue.put(("FILE_PROMPT", json.dumps({
            "sender": sender_username,
            "filename": filename,
            "prompt_id": prompt_id,
        })))

        pending_prompt["answered"].wait()
        with self.pending_prompts_lock:
            del self.pending_prompts[prompt_id]
        return pending_prompt["accepted"]


    # SENDING (sndf)

    def send_file(self, target_username, filepath):
        """Called from the GUI thread, so the actual work runs in its own thread."""
        threading.Thread(target=self._send_file_worker, args=(target_username, filepath), daemon=True).start()

    def _send_file_worker(self, target_username, filepath):
        if not os.path.isfile(filepath):
            self.network._show_output(f"SYSTEM > File not found: {filepath}")
            return

        target_address = self.network.get_user_address(target_username)
        if target_address is None:
            self.network._show_output(f"SYSTEM > {target_username} is not online.")
            return

        filename = os.path.basename(filepath)
        file_size = os.path.getsize(filepath)

        try:
            with socket.create_connection(target_address, timeout=PEER_CONNECT_TIMEOUT_SECONDS) as peer_socket:
                peer_socket.settimeout(None)   # the other user may take a while to answer the message box

                peer_socket.sendall(f"FILE_REQ|{self.network.username}|{filename}|{file_size}\n".encode("utf-8"))
                self.network._show_output(f'{self.network.username} > file sent "{filepath}"')

                peer_reader = peer_socket.makefile("rb")
                answer = peer_reader.readline().decode("utf-8").strip()
                if answer != "FILE_ACC":
                    self.network._show_output(f"{target_username} > file rejected")
                    return

                self.network._show_output(f"{target_username} > file accepted")
                with open(filepath, "rb") as file_to_send:
                    while True:
                        chunk = file_to_send.read(FILE_CHUNK_SIZE)
                        if not chunk:
                            break
                        peer_socket.sendall(chunk)

        except OSError as error:
            self.network._show_output(f"SYSTEM > Could not send {filename} to {target_username}: {error}")
            return

        self.network.write_log(f"{filename} to {self.network.describe_user(target_username)}")
        self.network._show_output(f'SYSTEM > File "{filename}" sent to {target_username}.')


    # RECEIVING (called by ClientNetwork in a P2P handler thread; it closes the socket itself)

    def handle_incoming_file(self, peer_socket, peer_reader, first_line):
        # The filename may contain '|', so the size is taken from the right side
        _, sender_username, filename_and_size = first_line.split("|", 2)
        filename, file_size = filename_and_size.rsplit("|", 1)
        filename = os.path.basename(filename)   # never write outside the download directory
        file_size = int(file_size)

        if not self._ask_user_to_accept(sender_username, filename):
            peer_socket.sendall(b"FILE_REJ\n")
            self.network._show_output(f'SYSTEM > Rejected "{filename}" from {sender_username}.')
            return

        peer_socket.sendall(b"FILE_ACC\n")
        self.network._show_output(f"{self.network.username} > file accepted")

        save_path = self._get_free_download_path(filename)
        remaining_bytes = file_size
        with open(save_path, "wb") as received_file:
            while remaining_bytes > 0:
                # Read from peer_reader, not peer_socket: the reader may already hold buffered bytes
                chunk = peer_reader.read(min(FILE_CHUNK_SIZE, remaining_bytes))
                if not chunk:
                    break
                received_file.write(chunk)
                remaining_bytes -= len(chunk)

        if remaining_bytes > 0:
            os.remove(save_path)
            self.network._show_output(f'SYSTEM > Transfer of "{filename}" from {sender_username} was interrupted.')
            return

        self.network.write_log(f"{filename} from {self.network.describe_user(sender_username)}")
        self.network._show_output(
            f'SYSTEM > Saved "{os.path.basename(save_path)}" from {sender_username} to the download folder.'
        )

    @staticmethod
    def _get_free_download_path(filename):
        """Returns download/<filename>, or download/<name> (1).<ext> etc. if the name is taken."""
        name, extension = os.path.splitext(filename)
        save_path = os.path.join(DOWNLOAD_DIRECTORY, filename)
        copy_number = 1
        while os.path.exists(save_path):
            save_path = os.path.join(DOWNLOAD_DIRECTORY, f"{name} ({copy_number}){extension}")
            copy_number += 1
        return save_path
