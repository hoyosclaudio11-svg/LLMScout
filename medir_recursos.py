# -*- coding: utf-8 -*-
"""Mide RAM y CPU del panel LLM Scout en ejecución.

Uso:
    python medir_recursos.py

Busca el proceso python/pythonw que corre scout.py y reporta working set,
memoria privada, CPU acumulada y % de la RAM total. Va por PowerShell
(Get-CimInstance) porque el cmdline del proceso solo se lee por WMI;
no requiere dependencias externas.

Letra chica del working set: incluye DLLs compartidas de Python/Tk que
otros procesos también mapean; la memoria privada es el costo "real" de
tener el panel abierto.
"""

import subprocess
import sys

PS = (
    "$ErrorActionPreference='Stop';"
    "$p = Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" "
    "| Where-Object { $_.CommandLine -like '*scout.py*' } | Select-Object -First 1;"
    "if (-not $p) { 'SIN_PROCESO'; exit };"
    "$h = Get-Process -Id $p.ProcessId;"
    "$os = Get-CimInstance Win32_OperatingSystem;"
    "'PID={0}' -f $h.Id;"
    "'WS_MB={0:N1}' -f ($h.WorkingSet64/1MB);"
    "'PRIV_MB={0:N1}' -f ($h.PrivateMemorySize64/1MB);"
    "'CPU_S={0:N1}' -f $h.TotalProcessorTime.TotalSeconds;"
    "'UP_H={0:N1}' -f ((Get-Date)-$h.StartTime).TotalHours;"
    "'TOTAL_MB={0}' -f [long]($os.TotalVisibleMemorySize/1KB);"
    "'LIBRE_MB={0:N0}' -f ($os.FreePhysicalMemory/1KB)"
)


def main():
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", PS],
            capture_output=True, text=True, timeout=30, check=True).stdout
    except Exception as e:
        print(f"no pude consultar el proceso: {e}")
        sys.exit(1)

    datos = {}
    for linea in out.splitlines():
        if "=" in linea:
            k, v = linea.split("=", 1)
            datos[k] = v

    if "PID" not in datos:
        print("no hay ninguna instancia de LLM Scout corriendo.")
        sys.exit(0)

    # PowerShell formatea con la configuración regional: es-AR usa coma decimal
    num = lambda s: float(s.replace(",", "."))
    ws = num(datos["WS_MB"])
    total = num(datos["TOTAL_MB"])
    print(f"LLM Scout (PID {datos['PID']}, encendido hace "
          f"{num(datos['UP_H']):.1f} h)")
    print(f"  RAM working set : {ws:>6.1f} MB  "
          f"({ws / total * 100:.1f} % de {total / 1024:.0f} GB)")
    print(f"  RAM privada     : {num(datos['PRIV_MB']):>6.1f} MB  (costo real)")
    print(f"  CPU acumulada   : {num(datos['CPU_S']):>6.1f} s")
    print(f"  RAM libre equipo: {datos['LIBRE_MB']:>6} MB")


if __name__ == "__main__":
    main()
