import dataclasses
from datetime import datetime, timedelta, time, date
from enum import Enum
from typing import Any

try:
    import pandas as pd
except ImportError:
    pass
import pathlib
import struct
from io import BytesIO, IOBase
import numpy as np
import argparse


@dataclasses.dataclass
class InteractiveReader:
    """
    Read a buffer with format strings like in struct, but one object at a time.
    This performs worse, but yields easier to read code.

    Example:
    ```
    r = InteractiveReader(f, byte_order="<")
    timestamp = r.read("d")
    annotation_count = r.read("i")
    block_count = r.read("i")
    first_annotation_location = r.read("i")
    fs = r.read("h")
    ```
    """
    buffer: IOBase
    byte_order: str = ""

    def read_tuple(self, format: str) -> tuple:
        s = struct.Struct(f"{self.byte_order}{format}")
        return s.unpack(self.buffer.read(s.size))

    def read_bytes(self, count: int):
        return self.buffer.read(count)

    def read(self, format: str):
        return self.read_tuple(format)[0]

    def read_iter(self, format: str, *, count: int = 1):
        s = struct.Struct(f"{self.byte_order}{format}")

        return (t[0] for t in s.iter_unpack(self.buffer.read(s.size * count)))


@dataclasses.dataclass
class SectionHeader:
    HEADER_LENGTH_BYTES = 16

    crc: int
    id: int
    length_bytes: int
    section_version: int
    protocol_version: int
    reserved: bytes

    @staticmethod
    def read(r: InteractiveReader) -> "SectionHeader":
        return SectionHeader(
            crc=r.read("H"),
            id=r.read("H"),
            length_bytes=r.read("I"),
            section_version=r.read("B"),
            protocol_version=r.read("B"),
            reserved=r.read_bytes(6),
        )


@dataclasses.dataclass
class SectionPointer:
    id: int
    length_bytes: int
    index_bytes: int

    @staticmethod
    def read(r: InteractiveReader) -> "SectionPointer":
        return SectionPointer(
            id=r.read("H"),
            length_bytes=r.read("I"),
            index_bytes=r.read("I") - 1,  # Indexes starting at 1.....
        )

    def extract_bytes(self, io: IOBase) -> bytes:
        io.seek(self.index_bytes)
        return io.read(self.length_bytes)


@dataclasses.dataclass
class InterpretedSection1:
    class Sex(Enum):
        Unknown = 0
        Male = 1
        Female = 2
        Unspecified = 9
        Other = 10

    @dataclasses.dataclass
    class Device:
        class DeviceType(Enum):
            Cart = 0
            SystemOrHost = 1

        institution_nr: int
        department_nr: int
        device_id: int
        device_type: DeviceType
        manufacturer_id: int  # 255 to specify as string, legacy systems print one of an enum
        text_model: str
        scp_ecg_protocol_rev_nr: int
        scp_ecg_protocol_compat_level: int
        language_support_bitmap: int
        capabilities_bitmap: int
        ac_mains_frequency_hz: int  # -1 for 'unspecified'
        reserved_for_future_use: bytes
        analysing_program_revision_nr: str
        acquisition_device_serial_nr: str
        acquisition_device_system_software_id: str
        acquisition_device_scp_software_id: str
        acquisition_device_manufacturer: str

    first_name: str = None
    last_name: str = None
    second_last_name: str = None
    patient_id: str = None

    age: timedelta = None
    date_of_birth: date = None

    height_cm: float = None
    weight_kg: float = None

    sex: Sex = None

    date_of_acquisition: date = None
    time_of_acquisition: time = None

    acquiring_institution: str = None
    analyzing_institution: str = None
    acquiring_department: str = None
    analyzing_department: str = None
    referring_physician: str = None
    latest_confirming_physician: str = None
    technician: str = None
    room: str = None

    highpass_filter_3db_hz: float = None
    lowpass_filter_3db_hz: float = None

    ecg_sequence_number: str = None

    acquiring_device: Device = None
    analyzing_device: Device = None

    free_text: str = None

    def interpret_tag(self, id: int, data: bytes):
        r = InteractiveReader(BytesIO(data))

        if id == 0:
            self.last_name = SCPFile.to_text(data)
        elif id == 1:
            self.first_name = SCPFile.to_text(data)
        elif id == 2:
            self.patient_id = SCPFile.to_text(data)
        elif id == 3:
            self.second_last_name = SCPFile.to_text(data)
        elif id == 4:
            age_num = r.read("H")
            age_unit = r.read("B")
            if age_unit == 0:
                return
            elif age_unit == 1:
                self.age = timedelta(
                    days=age_num * 365
                )  # This is not entirely correct, but it's close enough probably
            elif age_unit == 2:
                self.age = timedelta(
                    days=age_num * 30
                )  # This is not entirely correct, but it's close enough probably
            elif age_unit == 3:
                self.age = timedelta(weeks=age_num)
            elif age_unit == 4:
                self.age = timedelta(days=age_num)
            elif age_unit == 5:
                self.age = timedelta(hours=age_num)
            else:
                raise ValueError("Unexpected age unit:", age_unit)
        elif id == 5:
            self.date_of_birth = date(
                year=r.read("H"),
                month=r.read("B"),
                day=r.read("B"),
            )
        elif id == 6:
            height_num = r.read("H")
            height_unit = r.read("B")
            if height_unit == 0:
                return
            elif height_unit == 1:
                self.height_cm = height_num
            elif height_unit == 2:
                self.height_cm = height_num * 2.54
            elif height_unit == 3:
                self.height_cm = height_num / 10
            else:
                print("Unexpected height unit:", height_unit)
        elif id == 7:
            weight_num = r.read("H")
            weight_unit = r.read("B")
            if weight_unit == 0:
                return
            elif weight_unit == 1:
                self.weight_kg = weight_num
            elif weight_unit == 2:
                self.weight_kg = weight_num / 1000
            else:
                print("Unexpected weight unit:", weight_num)
        elif id == 8:
            try:
                self.sex = InterpretedSection1.Sex(r.read("B"))
            except ValueError:
                self.sex = InterpretedSection1.Sex.Other
        elif id == 14 or id == 15:
            def read_final_strings(r: InteractiveReader):
                length_of_first_string = r.read("B")  # Not needed?
                strings = r.read_bytes(len(data) - r.buffer.tell()).split(b'\0')
                return dict(
                    analysing_program_revision_nr=SCPFile.to_text(strings[0]),
                    acquisition_device_serial_nr=SCPFile.to_text(strings[1]),
                    acquisition_device_system_software_id=SCPFile.to_text(strings[2]),
                    acquisition_device_scp_software_id=SCPFile.to_text(strings[3]),
                    acquisition_device_manufacturer=SCPFile.to_text(strings[4]),
                )

            key = "acquiring_device" if id == 14 else "analyzing_device"
            setattr(self, key, InterpretedSection1.Device(
                institution_nr=r.read("H"),
                department_nr=r.read("H"),
                device_id=r.read("H"),
                device_type=InterpretedSection1.Device.DeviceType(r.read("B")),
                manufacturer_id=r.read("B"),
                text_model=SCPFile.to_text(r.read_bytes(6)),
                scp_ecg_protocol_rev_nr=r.read("B"),
                scp_ecg_protocol_compat_level=r.read("B"),
                language_support_bitmap=r.read("B"),
                capabilities_bitmap=r.read("B"),
                ac_mains_frequency_hz={
                    0: -1,
                    1: 50,
                    2: 60
                }.get(r.read("B"), None),
                reserved_for_future_use=r.read_bytes(16),
                **read_final_strings(r)
            ))
        elif id == 16:
            self.acquiring_institution = SCPFile.to_text(data)
        elif id == 17:
            self.analyzing_institution = SCPFile.to_text(data)
        elif id == 18:
            self.acquiring_department = SCPFile.to_text(data)
        elif id == 19:
            self.analyzing_department = SCPFile.to_text(data)
        elif id == 20:
            self.referring_physician = SCPFile.to_text(data)
        elif id == 21:
            self.latest_confirming_physician = SCPFile.to_text(data)
        elif id == 22:
            self.technician = SCPFile.to_text(data)
        elif id == 23:
            self.room = SCPFile.to_text(data)
        elif id == 25:
            self.date_of_acquisition = date(
                year=r.read("H"),
                month=r.read("B"),
                day=r.read("B"),
            )
        elif id == 26:
            self.time_of_acquisition = time(
                hour=r.read("B"),
                minute=r.read("B"),
                second=r.read("B"),
            )
        elif id == 27:
            self.highpass_filter_3db_hz = r.read("H") / 100
        elif id == 28:
            self.lowpass_filter_3db_hz = r.read("H")
        elif id == 30:
            self.free_text = SCPFile.to_text(data)
        elif id == 31:
            self.ecg_sequence_number = SCPFile.to_text(data)
        else:
            raise ValueError(f"Unsupported tag {id}")


@dataclasses.dataclass
class Section1:
    io: IOBase

    def read_tags(self) -> dict[int, bytes]:
        self.io.seek(0)
        r = InteractiveReader(self.io, "<")
        header = SectionHeader.read(r)

        result = dict()
        while header.length_bytes > r.buffer.tell():
            id = r.read("B")
            if id == 255:
                # 255 = "Header Terminator"
                # Header should contain one more length and may contain a padding byte
                # But since we had the terminator, it's fine to just break here.
                break
            data_len = r.read("H")
            if data_len == 0:
                continue  # Length of 0 means "not defined"
            result[id] = r.read_bytes(data_len)

        return result

    def read_tags_and_interpret(self) -> InterpretedSection1:
        tags = self.read_tags()

        result = InterpretedSection1()

        for id, data in tags.items():
            try:
                result.interpret_tag(id, data)
            except Exception as e:
                print(f"Error reading tag {id} ({data}):", e)

        return result


@dataclasses.dataclass
class HuffmanTable:
    table: dict[bytes, tuple[bool, int]]

    @staticmethod
    def default() -> "HuffmanTable":
        return HuffmanTable({
            b"0": (True, 0),
            b"100": (True, 1),
            b"101": (True, -1),
            b"1100": (True, 2),
            b"1101": (True, -2),
            b"11100": (True, 3),
            b"11101": (True, -3),
            b"111100": (True, 4),
            b"111101": (True, -4),
            b"1111100": (True, 5),
            b"1111101": (True, -5),
            b"11111100": (True, 6),
            b"11111101": (True, -6),
            b"111111100": (True, 7),
            b"111111101": (True, -7),
            b"1111111100": (True, 8),
            b"1111111101": (True, -8),
            b"1111111110": (False, 8),
            b"1111111111": (False, 16),
        })

    def decode(self, b: bytes) -> list[int]:
        values: list[int] = []
        s = format(int.from_bytes(b, "big"), "08b").encode("ascii")
        idx = 0
        end_idx = 0

        while end_idx < len(s):
            end_idx += 1
            if t := self.table.get(s[idx:end_idx], None):
                idx = end_idx

                if t[0]:
                    values.append(t[1])
                else:
                    end_idx += t[1]
                    bits_value = s[idx:end_idx]
                    idx = end_idx
                    value = int(bits_value[1:].decode("ascii"), base=2)
                    if bits_value[0] == b'1'[0]:
                        # 2's complement
                        value = value - (1 << (len(bits_value) - 1))
                    values.append(value)

        if idx != end_idx:
            raise ValueError(
                f"Warn: Last few bytes did not match an entry in the huffman table, data likely not encoded with this table: {s[idx:]}"
            )

        return values


@dataclasses.dataclass
class Section2:
    io: IOBase

    def read_tables(self) -> list[HuffmanTable]:
        self.io.seek(0)
        r = InteractiveReader(self.io, "<")
        header = SectionHeader.read(r)

        if header.length_bytes <= self.io.tell():
            return []  # Section undefined

        number_of_tables = r.read("H")
        if number_of_tables == 19999:
            return [HuffmanTable.default()]

        raise ValueError("Custom huffman tables are not supported yet")


lead_id_to_name: dict[int, str] = {
    1: "I",
    2: "II",
    3: "V1",
    4: "V2",
    5: "V3",
    6: "V4",
    7: "V5",
    8: "V6",
    9: "V7",
    10: "V2R",
    11: "V3R",
    12: "V4R",
    13: "V5R",
    14: "V6R",
    15: "V7R",
    16: "X",
    17: "Y",
    18: "Z",
    19: "CC5",
    20: "CM5",
    21: "Left Arm",
    22: "Right Arm",
    23: "Left Leg",
    24: "I",  # Not specified what the difference is to 1...
    25: "E",
    26: "A",
    27: "C",
    28: "M",
    29: "F",
    30: "H",
    31: "I-cal",
    32: "II-cal",
    33: "V1-cal",
    34: "V2-cal",
    35: "V3-cal",
    36: "V4-cal",
    37: "V5-cal",
    38: "V6-cal",
    39: "V7-cal",
    40: "V2R-cal",
    41: "V3R-cal",
    42: "V4R-cal",
    43: "V5R-cal",
    44: "V6R-cal",
    45: "V7R-cal",
    46: "X-cal",
    47: "Y-cal",
    48: "Z-cal",
    49: "CC5-cal",
    50: "CM5-cal",
    51: "Left Arm-cal",
    52: "Right Arm-cal",
    53: "Left Leg-cal",
    54: "I-cal",
    55: "E-cal",
    56: "A-cal",
    57: "C-cal",
    58: "M-cal",
    59: "F-cal",
    60: "H-cal",
    61: "III",
    62: "aVR",
    63: "aVL",
    64: "aVF",
    65: "-aVR",
    66: "V8",
    67: "V9",
    68: "V8R",
    69: "V9R",
    70: "D (Nehb-Dorsal)",
    71: "A (Nehb-Anterior)",
    72: "J (Nehb-Inferior)",
    73: "Defibrillator lead: anterior-lateral",
    74: "External pacing lead: anterior-posterior",
    75: "A1 (Auxiliary unipolar lead 1)",
    76: "A2 (Auxiliary unipolar lead 2)",
    77: "A3 (Auxiliary unipolar lead 3)",
    78: "A4 (Auxiliary unipolar lead 4)",
    79: "V8-cal",
    80: "V9-cal",
    81: "V8R-cal",
    82: "V9R-cal",
    83: "D-cal (cal for Nehb-Dorsal)",
    84: "A-cal (cal for Nehb-Anterior)",
    85: "J-cal (cal for Nehb-Inferior)",
}


@dataclasses.dataclass
class InterpretedSection3:
    @dataclasses.dataclass
    class LeadInfo:
        starting_sample_idx: int
        ending_sample_idx: int
        lead_idx: int
        lead_id: int

        def get_name(self) -> str:
            return lead_id_to_name.get(self.lead_id, f"Unknown lead {self.lead_idx}")

    leads: list[LeadInfo]
    is_reference_beat_subtraction_used_for_compression: bool
    reserved_flag: bool
    leads_all_simultaneously_recorded: bool
    # e.g. if 3, but total lead count is 6, then the first 3 are recorded together, and the subsequent 3 are recorded together
    number_of_simultaneously_recorded_leads: int


@dataclasses.dataclass
class Section3:
    io: IOBase

    def read_and_interpret(self) -> InterpretedSection3:
        r = InteractiveReader(self.io, "<")
        header = SectionHeader.read(r)

        lead_count = r.read("B")
        flag_byte = r.read("B")

        return InterpretedSection3(
            leads=[
                InterpretedSection3.LeadInfo(
                    starting_sample_idx=r.read("I") - 1,
                    ending_sample_idx=r.read("I") - 1,
                    lead_idx=i,
                    lead_id=r.read("B"),
                )
                for i in range(lead_count)
            ],
            is_reference_beat_subtraction_used_for_compression=flag_byte & 1,
            reserved_flag=flag_byte & 2,
            leads_all_simultaneously_recorded=flag_byte & 4,
            number_of_simultaneously_recorded_leads=flag_byte >> 3,
        )


@dataclasses.dataclass
class Section4Info:
    @dataclasses.dataclass
    class SubtractionZone:
        beat_type: int
        start_loc_idxs: int
        qrs_loc_idxs: int
        end_loc_idxs: int

    ref_beat_0_data_length_ms: int
    qrs_point_location_in_ref_beat_0_idxs: int
    number_of_qrs: int
    subtraction_zones: list[SubtractionZone]
    has_additional_data_that_wasnt_read: bool


@dataclasses.dataclass
class Section4:
    io: IOBase

    def read(self) -> Section4Info:
        r = InteractiveReader(self.io, "<")
        header = SectionHeader.read(r)

        ref_beat_0_data_length_ms = r.read("H")
        qrs_point_location_in_ref_beat_0_idxs = r.read("H")
        number_of_qrs = r.read("H")

        subtraction_zones = []
        if header.length_bytes > r.buffer.tell():
            # Has subtraction zones
            for i in range(number_of_qrs):
                subtraction_zones.append(Section4Info.SubtractionZone(
                    beat_type=r.read("H"),
                    start_loc_idxs=r.read("I"),
                    qrs_loc_idxs=r.read("I"),
                    end_loc_idxs=r.read("I"),
                ))

        return Section4Info(
            ref_beat_0_data_length_ms=ref_beat_0_data_length_ms,
            qrs_point_location_in_ref_beat_0_idxs=qrs_point_location_in_ref_beat_0_idxs,
            number_of_qrs=number_of_qrs,
            subtraction_zones=subtraction_zones,
            # TODO Read
            has_additional_data_that_wasnt_read=header.length_bytes > r.buffer.tell(),
        )


@dataclasses.dataclass
class DataContainer:
    sample_time_interval_us: int
    data_mv: list[np.ndarray]


@dataclasses.dataclass
class Section6:
    io: IOBase

    def read(self, tables: list[HuffmanTable], section3: InterpretedSection3) -> DataContainer:
        self.io.seek(0)
        r = InteractiveReader(self.io, "<")
        header = SectionHeader.read(r)

        amp_multiplier_nv = r.read("H")
        sample_time_interval_us = r.read("H")
        encoding = r.read(
            "B"
        )  # 0 = original, 1 = first difference, 2 = second difference
        compression = r.read("B")

        assert encoding in (0, 1, 2), f"Encoding not supported: {encoding}"
        assert compression == 0, f"Compression not supported: {compression}"
        assert not section3.is_reference_beat_subtraction_used_for_compression, "Reference beat subtraction not supported."

        compressed_lengths_byte = []
        for lead in section3.leads:
            compressed_lengths_byte.append(r.read("H"))

        datas_mv = []
        for compressed_length_byte in compressed_lengths_byte:
            if tables:
                if len(tables) > 1:
                    raise ValueError("Multi-huffman is not supported yet")
                data = np.array(tables[0].decode(r.read_bytes(compressed_length_byte)))
            else:
                assert (compressed_length_byte % 2) == 0
                data = []
                for i in range(compressed_length_byte // 2):
                    data.append(r.read("h"))
                data = np.array(data)

            if encoding == 1:
                # First value of the data is the actual value (rather than derivative).
                # This happens to be what cumsum does anyway.
                data = np.cumsum(data)
            elif encoding == 2:
                # First two values of the data are the actual values.
                # The rest is the second derivative.
                initial_values = data[:2]
                # Calculate first value of derivative, the rest is given in the signal.
                first_derivative_signal = np.cumsum(np.concatenate([[initial_values[1] - initial_values[0]], data[2:]]))
                # Use first value of signal, the rest is given in the derivative
                data = np.cumsum(np.concatenate([[initial_values[0]], first_derivative_signal]))

            datas_mv.append(data * (amp_multiplier_nv / 1000 / 1000))

        if self.io.tell() != header.length_bytes:
            print(f"Warn: Section 6 was not fully decoded ({self.io.tell()} / {header.length_bytes}).")

        return DataContainer(
            sample_time_interval_us=sample_time_interval_us, data_mv=datas_mv
        )


@dataclasses.dataclass
class BeatMeasurements:
    p_onset_ms: int
    p_offset_ms: int
    qrs_onset_ms: int
    qrs_offset_ms: int
    t_offset_ms: int
    p_axis_in_frontal_plane_deg: int
    qrs_axis_in_frontal_plane_deg: int
    t_axis_in_frontal_plane_deg: int


@dataclasses.dataclass
class InterpretedSection7:
    reference_beat_measurements: list[BeatMeasurements]

    average_rr_interval_ms: int
    average_pp_interval_ms: int


@dataclasses.dataclass
class Section7:
    io: IOBase

    def read(self) -> InterpretedSection7:
        self.io.seek(0)
        r = InteractiveReader(self.io, "<")
        header = SectionHeader.read(r)

        number_of_reference_beat_types = r.read("B")
        number_of_pacemaker_spikes = r.read("B")
        average_rr_interval_ms = r.read("H")
        average_pp_interval_ms = r.read("H")

        def real_measurement(measurement: int):
            return measurement if measurement not in (29999, 29998, 19999) else None

        beat_measurements = []
        for i in range(number_of_reference_beat_types):
            beat_measurements.append(BeatMeasurements(
                p_onset_ms=real_measurement(r.read("H")),
                p_offset_ms=real_measurement(r.read("H")),
                qrs_onset_ms=real_measurement(r.read("H")),
                qrs_offset_ms=real_measurement(r.read("H")),
                t_offset_ms=real_measurement(r.read("H")),
                p_axis_in_frontal_plane_deg=real_measurement(r.read("H")),
                qrs_axis_in_frontal_plane_deg=real_measurement(r.read("H")),
                t_axis_in_frontal_plane_deg=real_measurement(r.read("H")),
            ))
        return InterpretedSection7(
            # TODO Test if that's actually the reference beat, not per-qrs measurements
            reference_beat_measurements=beat_measurements,
            average_rr_interval_ms=real_measurement(average_rr_interval_ms),
            average_pp_interval_ms=real_measurement(average_pp_interval_ms),
        )


@dataclasses.dataclass
class SCPFreeStatements:
    class ConfirmationStatus(Enum):
        ORIGINAL_REPORT = 0
        CONFIRMED_REPORT = 1
        OVERREAD_REPORT_BUT_NOT_CONFIRMED = 2

    confirmation_status: ConfirmationStatus
    date_and_time: datetime
    statements: list[str]


@dataclasses.dataclass
class Section8:
    io: IOBase

    def read(self) -> SCPFreeStatements:
        self.io.seek(0)
        r = InteractiveReader(self.io, "<")
        header = SectionHeader.read(r)

        return SCPFreeStatements(
            confirmation_status=SCPFreeStatements.ConfirmationStatus(r.read("B")),
            date_and_time=datetime(
                year=r.read("H"),
                month=r.read("B"),
                day=r.read("B"),
                hour=r.read("B"),
                minute=r.read("B"),
                second=r.read("B")
            ),
            statements=[
                SCPFile.to_text(r.read_bytes(r.read("H")))
                for i in range(r.read("B"))
            ]
        )


@dataclasses.dataclass
class Section10Measurements:
    lead_id: int = None
    length_of_record: int = None
    p_duration_ms: int = None
    pr_interval_ms: int = None
    qrs_duration_ms: int = None
    qt_interval_ms: int = None
    q_duration_ms: int = None
    r_duration_ms: int = None
    s_duration_ms: int = None
    r_prime_duration_ms: int = None
    s_prime_duration_ms: int = None
    q_amplitude_uv: int = None
    r_amplitude_uv: int = None
    s_amplitude_uv: int = None
    r_prime_amplitude_uv: int = None
    s_prime_amplitude_uv: int = None
    j_point_amplitude_uv: int = None
    p_plus_amplitude_uv: int = None
    p_minus_amplitude_uv: int = None
    t_plus_amplitude_uv: int = None
    t_minus_amplitude_uv: int = None
    st_slope_uv_per_s: int = None
    p_morphology_description_id: int = None
    t_morphology_description_id: int = None
    iso_electric_segment_at_onset_of_qrs_ms: int = None
    iso_electric_segment_at_end_of_qrs_ms: int = None
    intrinsicoid_deflection_ms: int = None
    quality_code_reflecting_ecg_recording_conditions_id: int = None
    st_amplitude_uv_at_j_point_plus_20_ms: int = None
    st_amplitude_uv_at_j_point_plus_60_ms: int = None
    st_amplitude_uv_at_j_point_plus_1_16th_average_rr_inverval_ms: int = None
    st_amplitude_uv_at_j_point_plus_1_8th_average_rr_inverval_ms: int = None


@dataclasses.dataclass
class Section10:
    io: IOBase

    def read(self):
        self.io.seek(0)
        r = InteractiveReader(self.io, "<")
        header = SectionHeader.read(r)

        result: dict[int, Section10Measurements] = dict()
        while header.length_bytes > r.buffer.tell():
            id = r.read("H")
            length_bytes = r.read("H")
            section = r.read_bytes(length_bytes)
            measurement_reader = InteractiveReader(BytesIO(section), "<")
            measurements = []
            try:
                # Max 50 measurements, according to spec.
                # Anything afterwards is manufacturer specific and may not use the 2-byte schema
                for _ in range(50):
                    measurements.append(measurement_reader.read("H"))
            except:
                pass  # No more bytes, just stop
            result[id] = Section10Measurements(
                *measurements[:len(dataclasses.fields(Section10Measurements))]
            )

        return result


@dataclasses.dataclass
class SCPFile:
    @staticmethod
    def to_text(b: bytes) -> str:
        return b.decode("iso-8859-1").rstrip("\0")

    section_pointers: dict[int, SectionPointer]
    io: IOBase

    crc: int
    length_bytes: int

    @staticmethod
    def read(f: IOBase) -> "SCPFile":
        r = InteractiveReader(f, byte_order="<")

        crc = r.read("H")
        length_bytes = r.read("I")

        header = SectionHeader.read(r)

        pointers = []
        pointers_read = 0
        while header.length_bytes > r.buffer.tell():  # More as per length
            pointers_read += 1
            pointer = SectionPointer.read(r)
            if pointer.index_bytes < 0:
                assert pointer.index_bytes == -1
                assert pointer.length_bytes == 0
                continue  # Just included because of the SCP format, not actually here.
            pointers.append(pointer)

        if pointers_read < 12:
            print(f"Warn: Read just {pointers_read} pointers, at least 12 were expected.")

        return SCPFile(
            io=f,
            crc=crc,
            length_bytes=length_bytes,
            section_pointers={pointer.id: pointer for pointer in pointers},
        )

    def io_for_section(self, section: int) -> IOBase:
        return BytesIO(self.section_pointers.get(section, None).extract_bytes(self.io))

    def read_header_for_section(self, section: int) -> SectionHeader:
        return SectionHeader.read(InteractiveReader(self.io_for_section(section), "<"))

    def has_section(self, section: int) -> bool:
        if section not in self.section_pointers:
            return False
        return self.read_header_for_section(section).length_bytes > SectionHeader.HEADER_LENGTH_BYTES

    def populated_sections(self) -> list[int]:
        return [id for id in self.section_pointers if self.has_section(id)]

    def read_all_section_headers(self) -> list[SectionHeader]:
        return [SectionHeader.read(InteractiveReader(self.io_for_section(id), "<")) for id in self.section_pointers]

    def section1(self) -> Section1:
        return Section1(self.io_for_section(1))

    def section2(self) -> Section2:
        return Section2(self.io_for_section(2))

    def section3(self) -> Section3:
        return Section3(self.io_for_section(3))

    def section4(self) -> Section4:
        return Section4(self.io_for_section(4))

    def section6(self) -> Section6:
        return Section6(self.io_for_section(6))

    def section7(self) -> Section7:
        return Section7(self.io_for_section(7))

    def section8(self) -> Section8:
        return Section8(self.io_for_section(8))

    def section10(self) -> Section10:
        return Section10(self.io_for_section(10))

    def huffman_tables(self) -> list[HuffmanTable]:
        # [] = default = no huffman encodings used
        return self.section2().read_tables() if self.has_section(2) else []

    def section6_dataframe(self) -> "pd.DataFrame":
        tables = self.huffman_tables()
        section3 = self.section3().read_and_interpret()
        container = self.section6().read(tables, section3)

        assert section3.leads_all_simultaneously_recorded

        data_len = min(d.shape[0] for d in container.data_mv)
        if not all(d.shape[0] == data_len for d in container.data_mv):
            print("Warn: Data was of inhomogenous length:", [d.shape[0] for d in container.data_mv])

        return pd.DataFrame(
            np.array([d[:data_len] for d in container.data_mv]).T,
            index=(
                      np.arange(data_len)
                      * container.sample_time_interval_us
                  )
                  / 1000
                  / 1000,
            columns=[l.get_name() for l in section3.leads],
        )

    def write_wfdb_file(self, path):
        import wfdb
        path = pathlib.Path(path)

        tables = self.huffman_tables()
        section3 = self.section3().read_and_interpret()
        container = self.section6().read(tables, section3)

        wfdb.wrsamp(
            record_name=path.stem,
            fs=(1000 * 1000) / container.sample_time_interval_us,
            write_dir=str(path.parent),
            units=["mv"] * len(section3.leads),
            sig_name=[l.get_name() for l in section3.leads],
            p_signal=np.array(container.data_mv).T.astype(np.float64),
            fmt=["32"] * len(section3.leads),
        )


class Action(Enum):
    print_section_headers = 'print-section-headers'
    print_tags = 'print-tags'
    convert_to_mit = 'convert-to-mit'

arg_parser = argparse.ArgumentParser()
arg_parser.add_argument("action", type=Action, choices=list(Action))
arg_parser.add_argument("--input", type=pathlib.Path)
arg_parser.add_argument("--output", type=pathlib.Path, required=False)

def main():
    args = arg_parser.parse_args()

    if args.action == Action.print_section_headers:
        with args.input.open("rb") as f:
            file = SCPFile.read(f)
            headers = file.read_all_section_headers()
            for header in headers:
                print(f"Section {header.id:02d}: {header.length_bytes} bytes (section version: {header.section_version}, protocol version: {header.protocol_version})")
    if args.action == Action.print_tags:
        import pprint
        with args.input.open("rb") as f:
            file = SCPFile.read(f)
            tags = file.section1().read_tags_and_interpret()
            pprint.pp(dataclasses.asdict(tags))
    if args.action == Action.convert_to_mit:
        with args.input.open("rb") as f:
            file = SCPFile.read(f)
            file.write_wfdb_file(args.output)
        print(args.output)
    else:
        raise NotImplementedError()

if __name__ == "__main__":
    main()
