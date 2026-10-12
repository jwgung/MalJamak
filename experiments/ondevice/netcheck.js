fetch("https://www.google.com", { mode: "no-cors" }).then(() => "network: reachable", (e) => "network: blocked (" + e.message + ")")
