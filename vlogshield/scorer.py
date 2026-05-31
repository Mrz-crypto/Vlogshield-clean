from PIL import Image
from PIL.ExifTags import GPSTAGS, TAGS

# tag -> (name, points, severity, advice)
RISKS = {
    "GPS": ("GPS Coordinates", 45, "CRITICAL", "Exact location is embedded in this image."),
    "Make": ("Camera/Phone Brand", 10, "LOW", "Shows which device brand took the photo."),
    "Model": ("Camera/Phone Model", 15, "MEDIUM", "Shows your exact device model."),
    "Software": ("Software Used", 10, "LOW", "Shows which app or OS processed the image."),
    "DateTime": ("Original Timestamp", 10, "LOW", "Shows when the photo was taken."),
    "DateTimeOriginal": ("Shooting Timestamp", 10, "LOW", "Shows the exact capture time."),
    "Artist": ("Artist / Author Name", 25, "HIGH", "Your real name may be stored in the file."),
    "Copyright": ("Copyright String", 15, "MEDIUM", "May contain your name or handle."),
    "ImageDescription": ("Image Description", 10, "LOW", "Custom description text in the file."),
    "UserComment": ("User Comment", 20, "HIGH", "Comment field may hold personal info."),
    "SerialNumber": ("Device Serial Number", 30, "CRITICAL", "Unique hardware ID in metadata."),
    "LensSerialNumber": ("Lens Serial Number", 20, "HIGH", "Lens ID can link photos to you."),
    "BodySerialNumber": ("Body Serial Number", 30, "CRITICAL", "Camera body serial in metadata."),
    "CameraOwnerName": ("Camera Owner Name", 25, "HIGH", "Owner name registered on the camera."),
    "OwnerName": ("Owner Name", 25, "HIGH", "Owner name field has identifying info."),
    "XPAuthor": ("Windows Author Tag", 20, "HIGH", "Windows author metadata found."),
    "XPComment": ("Windows Comment Tag", 15, "MEDIUM", "Windows comment metadata found."),
    "XPSubject": ("Windows Subject Tag", 10, "LOW", "Windows subject metadata found."),
}
