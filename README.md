# Whisper

[![PyPI Version](https://img.shields.io/pypi/v/whisper-data?style=for-the-badge&logo=pypi&logoColor=fff)](https://pypi.org/project/whisper-data) [![GitHub Repo stars](https://img.shields.io/github/stars/the-can-of-soup/whisper?style=for-the-badge&logo=github&color=e3b341&label=GitHub)](https://github.com/the-can-of-soup/whisper)

A simple command-line utility to securely transfer files or data over WebSocket. Useful for one-time file transfers between devices, especially for large files or over the internet.


## Networking model

- **One peer is the server, and the other is the client.** The server must have an exposed port, e.g. via port forwarding or being on the LAN.
- **Data is transferred in one direction through a continuous stream.** Once the stream ends, the connection closes and the server shuts down.
- **Data may be transferred in either direction, regardless of who is the server/client.** This is useful because it requires only one peer to have port forwarding (or similar) set up, without the need to switch to the other peer for data flowing in the opposite direction.
- **The stream may continue indefinitely.** No "file size" or similar is sent as metadata; once a connection is established, the stream may continue to exist, sending data at whatever pace, until it ends or either side forcibly closes the connection.


## Installation

### From PyPI

Run: `pip install whisper-data`\
Alternatively you may use pipx: `pipx install whisper-data`

### From source (on Unix)

After cloning the repo, ensure that you have all dependencies listed in `pyproject.toml`, and zsh; then, run the `install.zsh` script.


## Usage

For full usage information, pass `--help` to the relevant command.

### `whisper` command

(Aliased as `wis`)

This is the main command of whisper.

### `whisper-certs` command

(Aliased as `wis-certs`)

This is a simple wrapper around `openssl` to create certificates, and as such it requires the `openssl` command to be installed in order to create these certificates.


## Example usage

### Create a certificate

```zsh
wis-certs create --name primary --owner soup --expire-in 100
```

### Transfer a file (server to client)

The server is assumed to have a key `~/.whisper/keys/primary.key` and matching certificate `~/.whisper/certs/primary.crt` with the common name `soup`, and the client the same with the common name `clippy`. Both peers must also have the other peer's certificate under any filename in their `~/.whisper/certs/` directory.
```zsh
# Server (run first)
wis --serve bee_movie_script.txt --who clippy

# Client
wis --connect-to wss://108.51.51.116:8409 --recv-to bee_movie_script.txt --who soup
```

### Transfer a file (client to server)

Same certificate setup as above.
```zsh
# Server (run first)
wis --serve --recv-to eviction_notice.md --who clippy

# Client
wis --connect-to wss://108.51.51.116:8409 eviction_notice.md --who soup
```


## Usage as a module

While usage as a module is not officially supported, you may import whisper's interfaces via the `whisper_data` module. All functions and classes are documented and type hinted.


## Credit

No AI was used; coded entirely by [a can of soup](https://github.com/the-can-of-soup) :3
