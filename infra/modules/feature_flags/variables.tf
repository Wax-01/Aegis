variable "environment" {
  type = string
}

variable "table_name" {
  type = string
}

variable "flags" {
  description = "Mapa FLAG => estado inicial en este ambiente."
  type        = map(bool)
}

variable "descriptions" {
  type = map(string)
  default = {
    ENABLE_DYNAMIC_SURGE_PRICING    = "Activa tarifas dinámicas en horas pico (multiplicador sobre la tarifa base)."
    ENABLE_FAST_CHARGE_BOOST        = "Habilita la reserva prioritaria de ultra-carga (conectores >= 300 kW)."
    SIMULATE_CHARGER_HARDWARE_FAULT = "Inyección de fallos: el cargador reporta falla física y se dispara el rollback SAGA."
  }
}
