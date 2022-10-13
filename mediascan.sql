
DROP TABLE IF EXISTS audio;
DROP TABLE IF EXISTS item;

CREATE TABLE ITEM (
	id integer primary key autoincrement,
	filename text(100) not null,
	filepath text(100) not null,
    vcodec text(10),
	filesize_mb integer,
	height integer,
	width integer,
	duration integer,
	fps text(7),
	color_space text(6),
	pix_format text(6),
	last_modified real
);

CREATE TABLE AUDIO (
	itemid integer,
	lang text(10),
	codec text(10),
	channel_layout text(10),
	isdefault integer DEFAULT 0,
	FOREIGN KEY(itemid) REFERENCES item(id)
	ON DELETE CASCADE
);

CREATE TABLE SUBTITLE (
	itemid integer,
	lang text(10),
	format text(10),
	isdefault integer DEFAULT 0,
	FOREIGN KEY(itemid) REFERENCES item(id)
	ON DELETE CASCADE
);
