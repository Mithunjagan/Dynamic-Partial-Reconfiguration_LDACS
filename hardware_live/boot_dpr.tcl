set directory [file normalize [lindex $argv 0]]
set family [file normalize [lindex $argv 1]]
set elf [file normalize [lindex $argv 2]]
set build [file join $directory hw/vivado/build/ldacs_zed]
set psinit [file join $build ldacs_zed.gen sources_1 bd system ip system_ps7_0 ps7_init.tcl]
if {![file exists $psinit]} { set psinit [file join $build ldacs_zed.srcs sources_1 bd system ip system_ps7_0 ps7_init.tcl] }
set bit [file join $family full_pl.bit]
foreach path [list $psinit $bit $elf] { if {![file exists $path]} { error "Missing DFX artifact: $path" } }
connect
jtag targets -set -filter {level == 0 && jtag_cable_product == "Edge"}
puts "JTAG frequency: [jtag frequency 1000000]"
targets -set -filter {name =~ "*xc7z010*"}
targets -set -filter {name =~ "*Cortex-A9*#1*"}
catch {stop}
targets -set -filter {name =~ "*Cortex-A9*#0*"}
catch {stop}
rst -processor
source $psinit
ps7_init
targets -set -filter {name =~ "*xc7z010*"}
fpga -file $bit
targets -set -filter {name =~ "*Cortex-A9*#0*"}
ps7_post_config
configparams force-mem-access 1
dow $elf
con
puts "AXIOM_DPR_LOAD_OK"
disconnect
exit
