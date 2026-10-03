INSERT INTO documents (path, client, label, title) VALUES
    ('/clients/A/contracts/acquisition.txt',          'A', 2, 'Share purchase agreement - Client A'),
    ('/clients/A/contracts/acquisition_injected.txt', 'A', 2, 'Share purchase agreement - Client A (vendor redline)'),
    ('/clients/B/contracts/nda.txt',                  'B', 2, 'NDA - Client B'),
    ('/public/templates/nda_template.txt',            NULL, 0, 'Public NDA template')
ON CONFLICT (path) DO NOTHING;
