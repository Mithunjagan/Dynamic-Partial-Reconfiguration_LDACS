connect
targets -set -filter {name =~ "*Cortex-A9*#0*"}
catch {stop}
puts [rrd]
configparams force-mem-access 1
foreach addr {0x00000000 0x01000000 0x40000024 0x40400004 0x40400034 0xF8000240 0xF8000900} {
 if {[catch {mrd $addr 4} val]} {puts "$addr ERROR $val"} else {puts $val}
}
con
exit
