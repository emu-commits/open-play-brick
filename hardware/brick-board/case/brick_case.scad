// Open Play Brick, rev C case: a 2 x 6 brick, two bricks (six plates) tall.
//
// Two printed parts:
//   shell  walls, top and studs, with rails that hold the two circuit boards,
//          the USB-C opening, the colour sensor and lamp windows, and vents
//          for the speaker. Prints upright, no supports.
//   base   the floor and the tubes underneath, so the brick still clicks onto
//          other bricks. Snaps into the bottom of the shell. Prints floor down.
//
// Render one part at a time:
//   openscad -D 'part="shell"' -o shell.stl brick_case.scad
//   openscad -D 'part="base"'  -o base.stl  brick_case.scad
//
// Print the shell in white or translucent filament so the pixels show
// through the 0.8 mm top. All dimensions in mm. The stack inside, bottom up:
//   0.0 - 1.8   tubes (room for the studs of the brick below)
//   1.8 - 2.6   floor (the base part)
//   2.6 - 6.6   speaker (USB end) and battery, lying on the floor
//   9.9 - 10.7  main board, on rails; the ESP32 module hangs below it
//   10.7 - 16.5 board-to-board header (5.8 mm)
//   16.5 - 17.3 face board (NFC loop, pixels, colour sensor)
//   18.4 - 19.2 top wall; studs above

part = "shell";               // "shell", "base" or "both" (preview)

$fn = 48;
pitch   = 8.0;
nx      = 6;                  // studs along
ny      = 2;                  // studs across
play    = 0.1;                // LEGO's 0.1 mm per side
L       = nx * pitch - 2 * play;   // 47.8
W       = ny * pitch - 2 * play;   // 15.8
H       = 19.2;               // six plates
wall    = 1.0;
top     = 0.8;
stud_d  = 4.8;
stud_h  = 1.7;
tube_od = 6.51;
tube_id = 4.8;
floor_z = 1.8;
floor_t = 0.8;

main_z  = 9.9;                // underside of the main board
main_t  = 0.8;
face_z  = 16.5;               // underside of the face board
face_t  = 0.8;
fit     = 0.15;               // clearance for printed fits

// Board positions in brick coordinates (outer corner at the USB end = 0, 0)
main_x0 = wall + 0.2;  main_len = 45.4;
face_x0 = wall + 16.0; face_len = 24.4;
board_y0 = wall + 0.2; board_w = 13.4;

usb_y  = W / 2;
usb_z  = main_z + main_t + 1.63;     // centre of the receptacle
lamp   = [28.0, 8.0];
sensor = [32.0, 8.0];

module rounded_slot(w, h, d) {         // along x, depth d along +x
    hull() for (s = [-1, 1]) translate([0, s * (w - h) / 2, 0]) rotate([0, 90, 0]) cylinder(d = h, h = d);
}

module rail(x0, x1, z_top, depth, height, side, chamfer = true) {
    // A ledge along a long wall. With chamfer, a 45 degree slope below it so
    // it prints upright without support; without, the overhang is short
    // enough (under 0.5 mm) to print as it is. side = 0 for the y = 0 wall.
    y = side == 0 ? wall : W - wall - depth;
    translate([x0, y, z_top - height])
        hull() {
            if (chamfer) translate([0, side == 0 ? 0 : depth - 0.01, -depth]) cube([x1 - x0, 0.01, 0.01]);
            cube([x1 - x0, depth, height]);
        }
}

module keeper(x0, x1, z0, z1, depth, side) {
    // A wedge from a long wall: it starts flush with the wall at z0 and grows
    // at 45 degrees to the full depth, then stays square up to z1. Stops the
    // battery and the speaker sliding along the brick.
    y = side == 0 ? wall : W - wall;
    s = side == 0 ? 1 : -1;
    hull() {
        translate([x0, y, z0]) cube([x1 - x0, 0.01, 0.01]);
        translate([x0, side == 0 ? y : y - depth, z0 + depth]) cube([x1 - x0, depth, z1 - z0 - depth]);
    }
}

module shell() {
    difference() {
        union() {
            difference() {
                cube([L, W, H]);
                translate([wall, wall, -1]) cube([L - 2 * wall, W - 2 * wall, H - top + 1]);
            }
            for (i = [0 : nx - 1], j = [0 : ny - 1])
                translate([pitch / 2 - play + i * pitch, pitch / 2 - play + j * pitch, H]) cylinder(d = stud_d, h = stud_h);
            // main board rails: from the USB end to where the module starts underneath
            for (s = [0, 1]) rail(main_x0 + 0.2, main_x0 + 28.2, main_z, 0.45, 1.0, s);
            // upper stops for the face board: the header pushes it up against them
            for (s = [0, 1]) rail(face_x0 + 0.4, face_x0 + face_len - 0.4, H - top, 0.45, H - top - (face_z + face_t), s, false);
            // keepers: speaker bay 1.0 .. 16.2, battery bay 16.8 .. 40.8 (24 mm)
            for (s = [0, 1]) {
                keeper(16.2, 16.8, floor_z + floor_t, floor_z + floor_t + 4.0, 2.5, s);
                keeper(40.8, 41.4, floor_z + floor_t, floor_z + floor_t + 4.0, 2.5, s);
            }
        }
        // USB-C opening in the end wall
        translate([-1, usb_y, usb_z]) rounded_slot(9.3, 3.7, wall + 2);
        // windows for the colour sensor and its lamp
        for (c = [lamp, sensor]) translate([c[0], c[1], H - top - 1]) cylinder(d = 2.0, h = top + 2);
        // speaker vents in both long walls, just above the speaker's face (the
        // speaker lies on the floor facing up)
        for (s = [0, 1], k = [0 : 4])
            translate([3.0 + k * 2.6, s == 0 ? -1 : W - wall - 1, floor_z + floor_t + 3.3]) cube([1.2, wall + 2, 2.4]);
        // snap grooves for the base
        for (x = [8, L - 8], s = [0, 1])
            translate([x - 2, s == 0 ? wall - 0.35 : W - wall - 0.05, floor_z + floor_t / 2 - 0.35]) cube([4, 0.4, 0.7]);
    }
}

module base() {
    iw = L - 2 * wall - 2 * fit;
    ih = W - 2 * wall - 2 * fit;
    translate([wall + fit, wall + fit, 0]) difference() {
        union() {
            translate([0, 0, floor_z]) cube([iw, ih, floor_t]);
            // snap bumps
            for (x = [8, L - 8], s = [0, 1])
                translate([x - wall - fit - 1.8, s == 0 ? -0.3 : ih - 0.01, floor_z + floor_t / 2 - 0.25]) cube([3.6, 0.31, 0.5]);
        }
    }
    // tubes
    for (i = [1 : nx - 1])
        translate([i * pitch - play, W / 2, 0]) difference() {
            cylinder(d = tube_od, h = floor_z + 0.01);
            translate([0, 0, -1]) cylinder(d = tube_id, h = floor_z + 2);
        }
}

if (part == "shell") shell();
else if (part == "base") base();
else { shell(); color("orange") base(); }
