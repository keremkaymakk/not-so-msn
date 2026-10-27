import socket
import sys
import threading
import json


online_users = {}
thread_lock = threading.Lock()
log_lock = threading.Lock()


def start_server(port):

    port = int(port)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:

        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        server_socket.bind(("0.0.0.0", port))
        server_socket.listen()

        print(f"The server is running on port {port}")

        while True:

            client_socket, client_address = server_socket.accept()

            client_thread = threading.Thread(target=handle_client, args=(client_socket, client_address))
            client_thread.start()



def handle_client(client_socket, client_address):
    
    username = None
    reader = None

    try:
        reader = client_socket.makefile("r", encoding="utf-8")

        while True:
            line = reader.readline().strip()

            if not line:
                break

            message = json.loads(line)

            if message["type"] == "DISCONNECT":
                break

            if message["type"] == "REGISTER":

                if username:
                    print(f"User {username} is already registered.")
                    break

                username = message["username"]
                ip = message["ip"]
                port = int(message["port"])

                with thread_lock:
                    online_users[username] = {"ip": ip, "port": port, "conn": client_socket}
                    log(ip, port, "connected")

                    print("All online users:")
                    for user in online_users:
                        print(f"{user}: {online_users[user]['ip']}:{online_users[user]['port']}")

                broadcast_online_users()

    except Exception as e:
        print(f"Error handling client {client_address}: {e}")

    finally:

        try:
            if username:
                remove_user(username, client_socket)

        finally:
            if reader:
                reader.close()

            client_socket.close()
            print(f"Connection with {client_address} closed.")



def broadcast_online_users():

    user_dict = {}
    connections = []
    
    with thread_lock:
        for user in online_users:
            user_dict[user] = {"ip": online_users[user]["ip"], "port": online_users[user]["port"]}
            connections.append(online_users[user]["conn"])
    packet = {"type": "USERLIST", "users": user_dict}
    json_packet = json.dumps(packet)
    encoded_packet = (json_packet + "\n").encode("utf-8")


    for conn in connections:
        try:
            conn.sendall(encoded_packet)
        except Exception as e:
            print(f"Error sending packet to {conn}: {e}")

    return packet

def remove_user(username, client_socket):

    removed = False

    with thread_lock:
        if username in online_users and online_users[username]["conn"] == client_socket:
            log(online_users[username]["ip"], online_users[username]["port"], "disconnected")
            del online_users[username]
            print(f"{username} has been removed from the online users list.")
            removed = True

    if removed:
        broadcast_online_users()


def log(ip, port, status):
    with log_lock:
        with open("server.log", "a", encoding="utf-8") as log_file:
            log_file.write(f"{ip} {port} {status}\n")

if __name__ == "__main__":

    port = sys.argv[1]
    start_server(port)

