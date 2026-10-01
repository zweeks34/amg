-- The standard list of things a schedule asks for and a receipt shows was done.
-- Codes are stable keys: schedules, line items and the receipt reader all refer
-- to them, so rename the name, never the code. Add new ones in a new migration.
--
-- default_action is what a line covering the type usually means when nothing
-- says otherwise: a part named on a receipt was replaced, a procedure was
-- performed, an inspection item was inspected.

INSERT INTO service_types (code, name, category, powertrains, default_action, sort) VALUES
    ('engine_oil',            'Engine oil',                     'Engine',                  'gas,hybrid',    'replace', 100),
    ('oil_filter',            'Oil filter',                     'Engine',                  'gas,hybrid',    'replace', 110),
    ('engine_air_filter',     'Engine air filter',              'Engine',                  'gas,hybrid',    'replace', 120),
    ('spark_plugs',           'Spark plugs',                    'Engine',                  'gas,hybrid',    'replace', 130),
    ('drive_belts',           'Drive belts',                    'Engine',                  'gas,hybrid',    'replace', 140),
    ('timing_belt',           'Timing belt',                    'Engine',                  'gas,hybrid',    'replace', 150),
    ('valve_clearance',       'Valve clearance',                'Engine',                  'gas,hybrid',    'perform', 160),
    ('engine_coolant',        'Engine coolant',                 'Engine',                  'gas,hybrid',    'replace', 170),
    ('cooling_system',        'Cooling system and hoses',       'Engine',                  'gas,hybrid,ev', 'inspect', 180),
    ('fuel_system',           'Fuel lines and connections',     'Engine',                  'gas,hybrid',    'inspect', 190),
    ('fuel_filter',           'Fuel filter',                    'Engine',                  'gas,hybrid',    'replace', 195),

    ('transmission_fluid',    'Transmission fluid',             'Drivetrain',              'gas,hybrid',    'replace', 200),
    ('differential_fluid',    'Differential fluid',             'Drivetrain',              'gas,hybrid,ev', 'replace', 210),
    ('transfer_case_fluid',   'Transfer case fluid',            'Drivetrain',              'gas,hybrid,ev', 'replace', 220),
    ('clutch',                'Clutch',                         'Drivetrain',              'gas,hybrid',    'inspect', 230),

    ('brake_fluid',           'Brake fluid',                    'Brakes',                  'gas,hybrid,ev', 'replace', 300),
    ('brake_pads',            'Brake pads',                     'Brakes',                  'gas,hybrid,ev', 'replace', 310),
    ('brake_rotors',          'Brake rotors',                   'Brakes',                  'gas,hybrid,ev', 'replace', 320),
    ('brake_system',          'Brake lines and parking brake',  'Brakes',                  'gas,hybrid,ev', 'inspect', 330),

    ('tire_rotation',         'Tire rotation',                  'Tires and wheels',        'gas,hybrid,ev', 'perform', 400),
    ('tires',                 'Tires',                          'Tires and wheels',        'gas,hybrid,ev', 'replace', 410),
    ('wheel_alignment',       'Wheel alignment',                'Tires and wheels',        'gas,hybrid,ev', 'perform', 420),
    ('wheel_balance',         'Wheel balance',                  'Tires and wheels',        'gas,hybrid,ev', 'perform', 430),
    ('tire_repair',           'Tire repair',                    'Tires and wheels',        'gas,hybrid,ev', 'perform', 440),
    ('wheel_bearings',        'Wheel bearings',                 'Tires and wheels',        'gas,hybrid,ev', 'inspect', 450),

    ('steering_suspension',   'Steering and suspension',        'Steering and suspension', 'gas,hybrid,ev', 'inspect', 500),
    ('axle_boots',            'Axle boots and joints',          'Steering and suspension', 'gas,hybrid,ev', 'inspect', 510),
    ('shocks_struts',         'Shocks and struts',              'Steering and suspension', 'gas,hybrid,ev', 'replace', 520),

    ('battery_12v',           '12-volt battery',                'Electrical',              'gas,hybrid,ev', 'replace', 600),
    ('wiper_blades',          'Wiper blades',                   'Electrical',              'gas,hybrid,ev', 'replace', 610),
    ('lights',                'Lights and bulbs',               'Electrical',              'gas,hybrid,ev', 'replace', 620),

    ('cabin_air_filter',      'Cabin air filter',               'Cabin',                   'gas,hybrid,ev', 'replace', 700),
    ('air_conditioning',      'Air conditioning',               'Cabin',                   'gas,hybrid,ev', 'perform', 710),

    ('inverter_coolant',      'Inverter coolant',               'Hybrid and EV',           'hybrid',        'replace', 800),
    ('hybrid_battery',        'Hybrid battery inspection',      'Hybrid and EV',           'hybrid',        'inspect', 810),
    ('hybrid_battery_filter', 'Hybrid battery cooling filter',  'Hybrid and EV',           'hybrid',        'replace', 820),
    ('ev_battery_coolant',    'Battery coolant',                'Hybrid and EV',           'ev',            'replace', 830),
    ('ev_battery',            'High-voltage battery inspection','Hybrid and EV',           'ev',            'inspect', 840),

    ('multipoint_inspection', 'Multi-point inspection',         'Inspections and other',   'gas,hybrid,ev', 'inspect', 900),
    ('state_inspection',      'State inspection',               'Inspections and other',   'gas,hybrid,ev', 'perform', 910),
    ('emissions_test',        'Emissions test',                 'Inspections and other',   'gas,hybrid',    'perform', 920),
    ('exhaust',               'Exhaust system',                 'Inspections and other',   'gas,hybrid',    'inspect', 930),
    ('recall',                'Recall or service campaign',     'Inspections and other',   'gas,hybrid,ev', 'perform', 940),
    ('software_update',       'Software update',                'Inspections and other',   'gas,hybrid,ev', 'perform', 950),
    ('other',                 'Other repair',                   'Inspections and other',   'gas,hybrid,ev', 'perform', 990);
