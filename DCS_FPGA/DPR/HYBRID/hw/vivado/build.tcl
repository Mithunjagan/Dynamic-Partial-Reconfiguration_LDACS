# Standard 7-series DFX flow; all RMs share ONE locked static implementation.
set origin [file normalize [file dirname [info script]]]
set hw [file normalize $origin/..]
set build_root [file normalize $origin/build_dpr]
if {[lsearch -exact $argv --static-hybrid]>=0} {set build_root [file normalize $origin/build_static]}
set out $build_root/dfx
file mkdir $out
# A verified family is immutable; recreate the project for a fresh token/build.
if {[file exists $out/routed_manifest.json]} {
 set mf [open $out/routed_manifest.json r];set previous [read $mf];close $mf
 if {[regexp {"pr_verify_passed"\s*:\s*true} $previous]} {error "Family already verified: package it or recreate_project for a new build"}
}
if {![file exists $build_root/source_snapshot.sha256]} {error "Run scripts/build_dpr.py to audit sources before implementation"}
set sf [open $build_root/source_snapshot.sha256 r];set source_sha [string trim [read $sf]];close $sf
# Invalidate the success marker before starting a new implementation.
set marker [open $out/routed_manifest.json w]
puts $marker { {"pr_verify_passed":false} }
close $marker
open_project $build_root/ldacs_zed/ldacs_zed.xpr
config_ip_cache -disable_cache
proc validate_routed {out rm} {
    report_drc -file $out/${rm}_drc.rpt
    set errors [get_drc_violations -quiet -filter {SEVERITY == Error || SEVERITY == "Critical Warning"}]
    if {[llength $errors]>0} {error "DFX DRC failed for $rm: $errors"}
    report_route_status -file $out/${rm}_route.rpt
    report_timing_summary -file $out/${rm}_timing.rpt
    report_utilization -file $out/${rm}_utilization.rpt
    report_utilization -hierarchical -file $out/${rm}_hierarchy.rpt
    report_power -file $out/${rm}_power_estimate.rpt
    foreach delay {max min} {
        set paths [get_timing_paths -quiet -delay_type $delay -max_paths 1]
        if {[llength $paths]>0&&[get_property SLACK [lindex $paths 0]]<0} {error "Timing failed: $rm ($delay)"}
    }
}
if {[lsearch -exact $argv --resume-static] < 0} {
    reset_run synth_1
    foreach run [get_runs -quiet *_synth_1] {reset_run $run}
    launch_runs synth_1 -jobs 4
    wait_on_run synth_1
}
if {[get_property PROGRESS [get_runs synth_1]] ne "100%"} {error "Static synthesis failed"}
open_run synth_1
set rps [get_cells -hier -filter {IS_BLACKBOX == 1 && REF_NAME =~ *rp_decoder}]
set topology_file $build_root/topology.txt
if {![file exists $topology_file]} {error "Recreate HYBRID project to select its topology"}
set topology_handle [open $topology_file r]
set topology [string trim [read $topology_handle]]
close $topology_handle
if {$topology eq "static_hybrid"} {
    if {[llength $rps]!=0} {error "Static HYBRID project still contains an RP black box"}
    if {[llength [get_cells -hier -filter {REF_NAME =~ *hybrid_core}]]!=1} {error "Expected one static HYBRID decoder"}
    opt_design
    place_design
    route_design
    validate_routed $out hybrid
    write_checkpoint -force $out/hybrid_routed.dcp
    write_bitstream -force -bin_file $out/hybrid.bit
    set tf [open $build_root/build_token.txt r]
    set token [string trim [read $tf]]
    close $tf
    set f [open $out/routed_manifest.json w]
    puts $f [format { {"schema":"ldacs_hybrid_static_routed_v1","part":"xc7z010clg400-1","build_token":%s,"implementation_passed":true,"critical_warnings_passed":true,"topology":"static_hybrid"} } $token]
    close $f
    close_project
    puts "STATIC_HYBRID_ROUTED_OK: no partial images; run scripts/package_images.py"
    exit
}
if {$topology ne "receiver_dpr"} {error "Unknown HYBRID topology"}
if {[llength $rps]!=1} {error "Expected one preserved rp_decoder black box: $rps"}
# Store the NAME string, not a Vivado object handle: close_project invalidates
# handles and otherwise read_checkpoint later receives the literal "null".
set rp_cell [get_property NAME [lindex $rps 0]]
write_checkpoint -force $out/static_synth.dcp
close_project
if {[lsearch -exact $argv --resume-rms] < 0} {
foreach rm {full_pl hybrid blank anchor} {
    create_project -in_memory -part xc7z010clg400-1
    read_verilog [glob $hw/shared/*.v]
    read_verilog [glob $hw/rm/$rm/*.v]
    synth_design -mode out_of_context -top rp_decoder -part xc7z010clg400-1
    write_checkpoint -force $out/${rm}_synth.dcp
    close_project
}
}
open_checkpoint $out/static_synth.dcp
read_checkpoint -cell $rp_cell $out/full_pl_synth.dcp
set_property HD.RECONFIGURABLE TRUE [get_cells $rp_cell]
source $origin/floorplan.tcl
opt_design
place_design
route_design
validate_routed $out full_pl
write_checkpoint -force $out/full_pl_routed.dcp
write_bitstream -force -bin_file $out/full_pl.bit
write_bitstream -force -bin_file -cell $rp_cell $out/full_pl_partial.bit
update_design -cell $rp_cell -black_box
lock_design -level routing
write_checkpoint -force $out/static_locked.dcp
close_design
foreach rm {hybrid blank anchor} {
    open_checkpoint $out/static_locked.dcp
    read_checkpoint -cell $rp_cell $out/${rm}_synth.dcp
    opt_design
    place_design
    route_design
    validate_routed $out $rm
    write_checkpoint -force $out/${rm}_routed.dcp
    pr_verify -full_check -file $out/${rm}_pr_verify.rpt $out/full_pl_routed.dcp $out/${rm}_routed.dcp
    write_bitstream -force -bin_file $out/${rm}.bit
    write_bitstream -force -bin_file -cell $rp_cell $out/${rm}_partial.bit
    close_design
}
set tf [open $build_root/build_token.txt r]
set token [string trim [read $tf]]
close $tf
set f [open $out/routed_manifest.json w]
puts $f [format { {"schema":"ldacs_dfx_routed_v1","part":"xc7z010clg400-1","build_token":%s,"rp_cell":"%s","pr_verify_passed":true,"critical_warnings_passed":true,"static_monitor_version":1,"hardware_source_sha256":"%s","configurations":["full_pl","hybrid","blank","anchor"]} } $token $rp_cell $source_sha]
close $f
puts "DFX_ROUTED_OK: run scripts/package_images.py"
