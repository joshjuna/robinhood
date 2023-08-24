# Setup on the EC2 server to connect to the server
* Documentation - https://bansalanuj.com/https-aws-ec2-without-custom-domain
* Install Caddy - https://caddyserver.com/docs/install
```
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install caddy
```

* Run this to allow caddy to download ssl certs

```sudo setcap CAP_NET_BIND_SERVICE=+eip $(which caddy)```

```caddy trust```

* Write to CaddyFile
```
54.187.200.254.nip.io {
        reverse_proxy localhost:8000
}
```

* Start the Caddy Server
```
caddy start
```

# Setup the Robinhood Service
* Put the Robinhood Service Configuration in /etc/systemd/system/robinhood.service
```
[Unit]
Description=Robinhood Server
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/robinhood
ExecStart=/home/ubuntu/robinhood/bin/gunicorn main:app -k uvicorn.workers.UvicornWorker --reload --access-logfile access.log --error-logfile error.log --capture-output
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
```

* Start the robinhood server
```
sudo systemctl start robinhood
```

# Run the server
### On AWS EC2 host
```
uvicorn main:app --reload
```
### Localhost
```
gunicorn -w 1 -k uvicorn.workers.UvicornWorker main:app
```

# Call the EC2 Server
### Prod: get_position
```
curl -H 'Content-Type: application/json; charset=utf-8' -d '{"symbol": "AAPL"}' -X POST 'https://54.187.200.254.nip.io/get_position'
```
### Localhost: get_position
```
curl -H 'Content-Type: application/json; charset=utf-8' -d '{"symbol": "AAPL"}' -X POST 'http://localhost:8000/get_position'
```

### Prod: place_order
```
curl -H 'Content-Type: application/json; charset=utf-8' -d '{"symbol" : "ACN", "time" : "2023-08-23T14:30:00Z", "price" : 315.00, "qty":1, "interval" : "D", "buy_plot":1}' -X POST 'https://54.187.200.254.nip.io/place_order'
```

# TradingView Notification Endpoint
```
https://54.187.200.254.nip.io/place_order
```

## TradingView Notification Body
```
{
"symbol" : "{{ticker}}",
"time" : "{{timenow}}",
"price" : {{close}},
"qty":50,
"interval" : {{interval}},
 "buy_plot":{{plot("Buy")}}
}
```

## Trading View Sample Notification
```
{
"symbol" : "BBBY",
"time" : "2023-02-23T14:30:00Z",
"price" : 1.61,
"qty":50,
"interval" : D,
 "buy_plot":-1
}
```
