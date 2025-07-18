"""Editing of masks, or replacement of automasks by edited masks"""

import os
import logging
import numpy as np
import napari
import dbdicom as db

from utils import data, radiomics


PATH = os.path.join(os.getcwd(), 'build')
datapath = os.path.join(PATH, 'dixon_2_data')
maskpath = os.path.join(PATH, 'kidneyvol_1_segment')
editpath = os.path.join(PATH, 'kidneyvol_3_edit')
os.makedirs(editpath, exist_ok=True)


# Set up logging
logging.basicConfig(
    filename=os.path.join(editpath, 'error.log'),
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

SITE = {
    '1128': 'Bari',
    '2128': 'Bordeaux',
    '6128': 'Bordeaux',
    '3128': 'Exeter',
    '4128': 'Leeds',
    '7128': 'Sheffield',
    '5128': 'Turku',
}


def edit_mask_with_napari(image_3d: np.ndarray, mask_3d: np.ndarray) -> np.ndarray:
    """
    Launches Napari to manually edit a 3D mask over a 3D image.

    Parameters:
    - image_3d: numpy.ndarray
        A 3D image array (shape: Z, Y, X)
    - mask_3d: numpy.ndarray
        A 3D mask array (shape: Z, Y, X)

    Returns:
    - edited_mask: numpy.ndarray
        The modified mask after editing in Napari.
    """
    if image_3d.shape != mask_3d.shape:
        raise ValueError("Image and mask must have the same shape.")
    
    # Ensure label image is integer type
    mask_3d = mask_3d.astype(np.int32)

    # Launch Napari
    viewer = napari.Viewer()

    # Display the image and the mask
    viewer.add_image(image_3d, name='Image')
    mask_layer = viewer.add_labels(mask_3d, name='Mask')

    # Set 2D slicing and coronal orientation for (X, Y, Z) image
    viewer.dims.ndisplay = 2
    viewer.dims.order = [2, 1, 0]  # Y, Z, X order for coronal view

    print("Edit the mask. Close the Napari window to return the edited mask.")

    # Run Napari event loop
    napari.run()

    # Return the edited mask
    return mask_layer.data


def edit_auto_masks(site):

    sitedatapath = os.path.join(datapath, site, "Patients") 
    sitemaskpath = os.path.join(maskpath, site, "Patients")
    siteeditpath = os.path.join(editpath, site, "Patients")

    # List of selected dixon series
    record = data.dixon_record()

    # Loop over the autogenerated masks
    for mask_series in db.series(sitemaskpath):

        # Patient and output study
        patient = mask_series[1]
        study = mask_series[2][0]

        # Skip if the edited masks already exist
        edited_mask_study = [siteeditpath, patient, (study, 0)]
        edited_mask_series = edited_mask_study + [(f'kidney_masks', 0)]
        if edited_mask_series in db.series(edited_mask_study):
            continue

        # Get the out-phase sequence
        sequence = data.dixon_series_desc(record, patient, study)
        series_op = [sitedatapath, patient, study, sequence + '_out_phase']
        op = db.volume(series_op)

        # Get the auto-mask
        auto_mask_series = [sitemaskpath, patient, study, f'kidney_masks']
        auto_mask = db.volume(auto_mask_series)

        # Edit the mask and save
        try:
            edited_mask = edit_mask_with_napari(op.values, auto_mask.values)
        except Exception as e:
            logging.error(f"{patient} {study} error editing mask: {e}")
        else:
            # TODO: in measure step, pick up edited from here and original if not edited
            vol = (edited_mask.astype(np.int16), auto_mask.affine)
            if not np.array_equal(op.values, vol[0]):
                db.write_volume(vol, edited_mask_series, ref=series_op)


def convert_manual_masks():
    # This converts masks made by Hugo using the original pipeline (downloaded from google drive)

    # Extract all sub folders if needed
    manual_mask_path = "C:\\Users\\md1spsx\\Documents\\Data\\iBEAt\\Edited_kidney_masks_2025_06_25"
    restored_manual_mask_path = "C:\\Users\\md1spsx\\Documents\\Data\\iBEAt\\Edited_kidney_masks_2025_06_25_restore"
    # db.restore(manual_mask_path, restored_manual_mask_path)

    # Loop over all subfolders
    for name in os.listdir(restored_manual_mask_path):
        full_path = os.path.join(restored_manual_mask_path, name)
        if os.path.isdir(full_path):
            patient_id = name[:8]
            study = 'Followup' if 'followup' in name else 'Baseline'
            # Get the dixon reference geometry
            all_series = db.series(full_path)
            for dixon in all_series:
                if dixon[-1][0] == "Dixon_post_contrast_out_phase":
                    break
                if dixon[-1][0] == "Dixon_out_phase":
                    break
            vol_dixon = db.volume(dixon)
            # Get kidneys label image
            vol_rk = None
            vol_lk = None
            for series in all_series:
                if series[-1][0] == 'RK_ed': #2
                    vol_rk = db.volume(series)
                    # Needs rescaling to currect incrorrect rescale slope in DICOM save
                    v0, v1 = np.min(vol_rk.values), np.max(vol_rk.values)
                    if v1>v0:
                        values = (vol_rk.values-v0)/(v1-v0)
                        vol_rk.set_values(values)
                    vol_rk = vol_rk.slice_like(vol_dixon)
                elif series[-1][0] == 'LK_ed': #1
                    vol_lk = db.volume(series)
                    # Needs rescaling to currect incrorrect rescale slope in DICOM save
                    v0, v1 = np.min(vol_lk.values), np.max(vol_lk.values)
                    if v1>v0:
                        values = (vol_lk.values-v0)/(v1-v0)
                        vol_lk.set_values(values)
                    vol_lk = vol_lk.slice_like(vol_dixon)
            if vol_rk is None:
                if vol_lk is None:
                    continue
                else:
                    values = vol_lk.values
                    values[values<0.5]=0
                    values[values>=0.5]=1
            else:
                values = vol_rk.values
                values[values<0.5]=0
                values[values>=0.5]=2
                if vol_lk is not None:
                    values_lk = vol_lk.values
                    values_lk[values_lk<0.5]=0
                    values_lk[values_lk>=0.5]=1
                    values += values_lk
            # Save kidney label as DICOM
            values = radiomics.largest_cluster_label(values)
            vol = (values.astype(np.int16), vol_dixon.affine)
            siteeditpath = os.path.join(editpath, SITE[patient_id[:4]], 'Patients')
            os.makedirs(siteeditpath, exist_ok=True)
            vol_series = [siteeditpath, patient_id, (study, 0), ('kidney_masks', 0)]
            db.write_volume(vol, vol_series, ref=dixon)



def all():
    edit_auto_masks('Bari')
    edit_auto_masks('Leeds')
    edit_auto_masks('Sheffield')


if __name__=='__main__':
    # edit_auto_masks('Bari')
    convert_manual_masks()
