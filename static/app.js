const STATUS = {
  AVAILABLE: "Libre",
  OCCUPIED: "Ocupado",
  UNKNOWN: "Sin lectura",
};

const GATES = {
  CLOSED: "Cerrada",
  OPENING: "Abriendo",
  OPEN: "Abierta",
  CLOSING: "Cerrando",
};

const EVENTS = {
  BOOT: "La placa arrancó",
  VEHICLE_DETECTED: "Vehículo detectado",
  ACCESS_DENIED: "Acceso negado",
  GATE_OPENED: "La barrera empieza a abrir",
  PASSAGE_CONFIRMED: "El auto pasó la barrera",
  PASSAGE_TIMEOUT: "El auto no llegó a la barrera",
  GATE_CLOSED: "La barrera se cerró",
  SLOT_CHANGED: "Cambió un cajón",
  RESET: "Reinicio de la placa",
  ERROR: "La placa rechazó un mensaje",
};

const WHERE = { ENTRY: "entrada", EXIT: "salida", REMOTE: "remoto", ARDUINO: "placa" };
const WHY = { NO_SPACE: "no hay lugar", NOT_READY: "los cajones aún no están listos" };

function gateClass(value) {
  if (value === "OPEN") return "open";
  if (value === "OPENING" || value === "CLOSING") return "moving";
  return "closed";
}

function paintArm(id, value) {
  const arm = document.getElementById(id);
  arm.classList.remove("open", "closed", "moving");
  arm.classList.add(gateClass(value));
}

function describe(item) {
  if (item.event === "SLOT_CHANGED") {
    return "Cajón " + item.slot + ": " + (STATUS[item.status] || item.status);
  }
  let text = EVENTS[item.event] || item.event;
  if (item.location && WHERE[item.location]) text += " · " + WHERE[item.location];
  if (item.reason && WHY[item.reason]) text += " · " + WHY[item.reason];
  else if (item.reason) text += " · " + item.reason;
  return item.at + "  " + text;
}

function render(data) {
  const link = document.getElementById("link");
  link.textContent = data.connected ? "Arduino conectado" : "Sin Arduino";
  link.className = "link " + (data.connected ? "on" : "off");

  data.slots.forEach(function (slot) {
    const card = document.querySelector('[data-slot="' + slot.id + '"]');
    card.className = "stall " + String(slot.status || "UNKNOWN").toLowerCase();
    card.querySelector(".label").textContent = STATUS[slot.status] || slot.status;
    card.querySelector(".car").hidden = slot.status !== "OCCUPIED";
    const cm = card.querySelector(".cm");
    if (slot.cm === null || slot.cm === undefined) cm.textContent = "";
    else if (slot.cm < 0) cm.textContent = "sin eco";
    else cm.textContent = slot.cm + " cm";
  });

  document.getElementById("free").textContent = data.available;
  document.getElementById("occupied").textContent = data.occupied + " ocupados";
  document.getElementById("gate").textContent = GATES[data.gate] || data.gate;
  document.getElementById("exit-gate").textContent = GATES[data.exit_gate] || data.exit_gate;
  paintArm("arm-entry", data.gate);
  paintArm("arm-exit", data.exit_gate);

  const known = data.slots.every(function (slot) { return slot.status !== "UNKNOWN"; });
  const lamp = document.getElementById("lamp");
  lamp.className = "lamp";
  if (known && data.available === 3) {
    lamp.classList.add("green");
    lamp.textContent = "Los tres cajones libres";
  } else if (known && data.available === 0) {
    lamp.classList.add("red");
    lamp.textContent = "Estacionamiento lleno";
  } else {
    lamp.classList.add("yellow");
    lamp.textContent = known ? "Hay lugares libres" : "Sin lectura firme";
  }

  const dots = {
    "dot-entry-1": data.entry && data.entry[0],
    "dot-entry-2": data.entry && data.entry[1],
    "dot-exit-1": data.exit && data.exit[0],
    "dot-exit-2": data.exit && data.exit[1],
    "dot-barrier": data.barrier,
    "dot-exit-barrier": data.exit_barrier,
  };
  Object.keys(dots).forEach(function (id) {
    document.getElementById(id).classList.toggle("on", dots[id] === 1);
  });

  const list = document.getElementById("events");
  list.innerHTML = "";
  (data.events || []).forEach(function (item) {
    const line = document.createElement("li");
    line.textContent = describe(item);
    list.appendChild(line);
  });

  const updated = document.getElementById("updated");
  if (data.serial_error && !data.connected) {
    updated.textContent = data.serial_error;
  } else if (data.received_at) {
    updated.textContent = "Último mensaje a las " + data.received_at;
  }
}

function connect() {
  const source = new EventSource("/api/stream");
  source.onmessage = function (message) {
    render(JSON.parse(message.data));
  };
  source.onerror = function () {
    document.getElementById("link").textContent = "Reconectando…";
  };
}

document.querySelectorAll("[data-cmd]").forEach(function (button) {
  button.addEventListener("click", function () {
    const note = document.getElementById("action-note");
    fetch("/api/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cmd: button.dataset.cmd }),
    }).then(function (response) {
      return response.json().then(function (body) {
        note.textContent = body.ok ? "" : (body.error || "No se pudo enviar");
      });
    }).catch(function () {
      note.textContent = "No se pudo enviar";
    });
  });
});

connect();
