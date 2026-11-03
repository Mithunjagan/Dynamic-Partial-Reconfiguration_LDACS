# Volatile JTAG boot only. Does not modify QSPI, SD, or existing build products.
set mode [lindex $argv 0]
set root [file normalize [lindex $argv 1]]
set elf [file normalize [lindex $argv 2]]
if {$mode ni {PS PL HYBRID}} { error "Unknown architecture" }
if {$mode eq "PS"} { set design [file join $root FULL_PS] } elseif {$mode eq "PL"} { set design [file join $root FULL_PL] } else { set design $root }
set build [file join $design hw vivado build ldacs_zed]
set bit [file join $build ldacs_zed.runs impl_1 system_wrapper.bit]
set psinit [file join $build ldacs_zed.gen sources_1 bd system ip system_ps7_0 ps7_init.tcl]
if {![file exists $psinit]} { set psinit [file join $build ldacs_zed.srcs sources_1 bd system ip system_ps7_0 ps7_init.tcl] }
foreach path [list $bit $psinit $elf] { if {![file exists $path]} { error "Missing artifact: $path" } }
proc event {stage message} { puts [format "AXIOM_STAGE:%d:%s" $stage $message]; flush stdout }
connect
jtag targets -set -filter {level == 0 && jtag_cable_product == "Edge"}
puts "JTAG frequency: [jtag frequency 1000000]"
targets -set -filter {name =~ "*xc7z010*"}
targets -set -filter {name =~ "*Cortex-A9*#0*"}
rst -system -stop
after 2000
targets -set -filter {name =~ "*Cortex-A9*#1*"}
catch {stop}
targets -set -filter {name =~ "*Cortex-A9*#0*"}
catch {stop}
event 1 "PS system reset via JTAG; CPU1 halted (not a physical POR_B cold boot)"
# Keep the previous PL/DMA configuration from accessing DDR during PS init.
configparams force-mem-access 1
mwr 0xF8000008 0x0000DF0D
mwr 0xF8000240 0x0000000F
mwr 0xF8000900 0x00000000
mwr 0xF8000004 0x0000767B
source $psinit
ps7_init
event 2 "Board-generated PS initialization completed: DDR/MIO/PLL"
targets -set -filter {name =~ "*xc7z010*"}
fpga -file $bit
if {$mode eq "PS"} { event 3 "PS-only blank fabric image programmed; no decoder or AXI DMA" } else { event 3 "Architecture-specific routed FPGA bitstream programmed via JTAG" }
targets -set -filter {name =~ "*Cortex-A9*#0*"}
ps7_post_config
configparams force-mem-access 1
event 4 "PS post-configuration complete; loading DDR firmware at 0x01000000"
dow $elf
con
event 5 "Firmware started; awaiting real UART decode and architecture-ID verification"
puts "AXIOM_LOAD_OK"
disconnect
exit
